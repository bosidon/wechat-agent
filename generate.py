#!/usr/bin/env python3
"""
公众号文章生成Agent - 自动选择书目/话题/角度，生成高质量文章
"""

import json
import os
import random
import re
import hashlib
import time
import base64
import requests
from datetime import datetime
from pathlib import Path

# ============================================================
# 配置
# ============================================================
BASE_DIR = Path(__file__).parent
CONTENT_WHEEL_PATH = BASE_DIR / "content-wheel.json"
ARTICLES_DIR = BASE_DIR / "articles"
ENV_PATH = Path("/var/www/.env")

# 灵修站本地API
LINGXIU_BASE = "http://localhost:3099"

# DeepSeek API
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"

# 飞书
FEISHU_TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
FEISHU_MSG_URL = "https://open.feishu.cn/open-apis/im/v1/messages"
FEISHU_USER_OPEN_ID = "ou_2de0e765d00b32cb928b7e9c195a0651"


def load_env():
    """从 /var/www/.env 读取环境变量"""
    env = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def load_content_wheel():
    """读取内容轮盘配置"""
    with open(CONTENT_WHEEL_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_content_wheel(wheel):
    """保存内容轮盘配置（更新recent_used）"""
    with open(CONTENT_WHEEL_PATH, "w", encoding="utf-8") as f:
        json.dump(wheel, f, ensure_ascii=False, indent=2)


def select_book(wheel):
    """
    选择书目 - 不重复最近2篇用过的
    返回 (book_dict, updated_wheel)
    """
    pool = wheel["books"]["pool"]
    recent = wheel["books"].get("recent_used", [])
    max_history = wheel["books"].get("max_history", 3)

    # 过滤掉最近用过的
    available = [b for b in pool if b["name"] not in recent]
    if not available:
        # 如果都用过了，清空历史重选
        wheel["books"]["recent_used"] = []
        available = pool

    # 按权重随机选择
    weights = [b["weight"] for b in available]
    chosen = random.choices(available, weights=weights, k=1)[0]

    # 更新历史
    recent.append(chosen["name"])
    if len(recent) > max_history:
        recent = recent[-max_history:]
    wheel["books"]["recent_used"] = recent

    return chosen, wheel


def select_theme(wheel):
    """
    选择话题分类 + 具体话题
    返回 (category_dict, topic_string, updated_wheel)
    """
    categories = wheel["themes"]["categories"]

    # 过滤掉最近用过的话题分类
    available_cats = []
    for cat in categories:
        recent = cat.get("recent_used", [])
        available_examples = [e for e in cat["examples"] if e not in recent]
        if available_examples:
            available_cats.append((cat, available_examples))

    if not available_cats:
        # 重置所有recent_used
        for cat in categories:
            cat["recent_used"] = []
        available_cats = [(cat, cat["examples"]) for cat in categories]

    # 随机选一个分类
    cat, examples = random.choice(available_cats)
    # 随机选一个具体话题
    topic = random.choice(examples)

    # 更新历史
    cat.setdefault("recent_used", []).append(topic)
    max_history = wheel["themes"].get("max_history", 2)
    if len(cat["recent_used"]) > max_history:
        cat["recent_used"] = cat["recent_used"][-max_history:]

    return cat, topic, wheel


def select_angle(wheel):
    """
    选择写作角度 - 不重复最近3篇
    返回 (angle_dict, updated_wheel)
    """
    pool = wheel["angles"]["pool"]
    recent = wheel["angles"].get("recent_used", [])
    max_history = wheel["angles"].get("max_history", 3)

    available = [a for a in pool if a["name"] not in recent]
    if not available:
        wheel["angles"]["recent_used"] = []
        available = pool

    chosen = random.choice(available)

    recent.append(chosen["name"])
    if len(recent) > max_history:
        recent = recent[-max_history:]
    wheel["angles"]["recent_used"] = recent

    return chosen, wheel


def select_scenario(wheel):
    """选择案例场景"""
    scenarios = wheel["examples"]["preferred_scenarios"]
    avoid = wheel["examples"]["avoid_patterns"]
    # 简单随机选（避免使用已avoid的模式）
    return random.choice(scenarios)


def select_hook():
    """选择开头钩子类型"""
    hooks = [
        ("场景代入", "用一个具体的日常场景让读者代入"),
        ("反常识", "挑战一个常见认知，引发好奇"),
        ("数据/事实", "用一个有趣的事实或数据开头"),
        ("金句开头", "用书中的经典句子开头"),
        ("提问式", "用一个问题引发读者思考"),
        ("故事式", "用一个小故事引入话题"),
        ("对比式", "用对比引发思考"),
        ("时间线", "用时间线讲述变化"),
    ]
    return random.choice(hooks)


def select_structure():
    """选择文章结构"""
    structures = [
        ("standard", "标准解读型", "开头→核心观点+原文→解读+案例→练习→引导"),
        ("story", "故事引入型", "故事→话题→书中印证→反思→行动建议"),
        ("debate", "观点碰撞型", "争议观点→正方→反方→书中答案→你的立场"),
        ("listicle", "清单型", "引子→5-7个要点→总结→引导"),
        ("qa", "问答型", "读者提问→分析→书中观点→解决方案→鼓励"),
        ("contrast", "对比型", "两种误解→真相→书中怎么说→领悟→练习"),
    ]
    return random.choice(structures)


def select_tone():
    """选择语气风格"""
    tones = [
        ("温暖朋友型", "用「你」「我」，感叹号，偶尔emoji，像朋友聊天"),
        ("沉思独白型", "用「我们」，多问句，像写日记一样沉思"),
        ("活力分享型", "短句多，破折号，像兴奋地分享一个发现"),
    ]
    return random.choice(tones)


def fetch_book_content(book_id):
    """
    从灵修站API获取书的精读内容
    返回 categories 和 themes 数据
    """
    result = {"categories": [], "themes": {}, "error": None}

    try:
        # 获取分类
        r = requests.get(f"{LINGXIU_BASE}/api/books/{book_id}/aideep-categories", timeout=10)
        if r.status_code == 200:
            data = r.json()
            if data.get("success"):
                result["categories"] = data.get("data", [])
    except Exception as e:
        result["error"] = f"获取分类失败: {e}"
        return result

    # 获取每个分类下的主题（最多取前3个分类）
    for cat in result["categories"][:3]:
        cat_id = cat.get("id") or cat.get("categoryId")
        if not cat_id:
            continue
        try:
            r = requests.get(
                f"{LINGXIU_BASE}/api/books/{book_id}/aideep-themes/{cat_id}",
                timeout=10,
            )
            if r.status_code == 200:
                data = r.json()
                if data.get("success"):
                    result["themes"][cat_id] = data.get("data", [])
        except Exception as e:
            print(f"  获取分类{cat_id}主题失败: {e}")

    return result


def fetch_theme_detail(book_id, theme_id):
    """获取主题详情"""
    try:
        r = requests.get(
            f"{LINGXIU_BASE}/api/books/{book_id}/aideep-theme/{theme_id}",
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            if data.get("success"):
                return data.get("data", {})
    except Exception as e:
        print(f"  获取主题详情失败: {e}")
    return None


def build_system_prompt(structure, tone, hook, angle, scenario, book_name, topic):
    """构建系统提示词"""
    return f"""你是「仙宝心灵成长」公众号的专职内容创作Agent。

## 品牌定位
- 名称: 仙宝心灵成长
- 调性: 温暖、真诚、有深度但不说教，像一个懂灵修的朋友在聊天
- 受众: 25-45岁对心灵成长感兴趣的人

## 本次写作参数
- 书目: 《{book_name}》
- 话题: {topic}
- 写作角度: {angle["name"]} - {angle["desc"]}
- 文章结构: {structure[1]} - {structure[2]}
- 语气风格: {tone[0]} - {tone[1]}
- 开头钩子: {hook[0]}
- 案例场景: {scenario}

## 写作规则
1. 总字数1000-1500字
2. 原文摘录不超过20%，必须标注出处
3. 原创解读占50%以上
4. 用自己的话重新诠释，加入现代生活案例
5. 每篇结尾提供1-2个可操作的练习
6. 引导语：「想看完整精读？访问 lingxiu.xianbao.online」

## 禁用词（绝对不能出现）
换句话说、值得一提的是、总而言之、综上所述、不得不承认、
众所周知、毫无疑问、显而易见、在这个快节奏的时代、
在这个信息爆炸的时代、让我们一起来、接下来让我们、
你是否曾经、其实、本质上、从本质上来说、归根结底

## 必须注入的元素（至少3项）
- 个人经历（具体事件）
- 情绪表达（开心/困惑/惊讶/感动）
- 个人观点（明确说「我认为」「我的理解是」）
- 具体细节（时间/地点/人物/对话）
- 自嘲/幽默
- 读者互动（提问/邀请评论）
- 不完美表达（口语/俚语）
- 个人偏好

## 句式要求
- 每3段至少1个短句（<10字）
- 每5段至少1个问句
- 避免连续3句以上相同句式开头
- 段落长度要有变化（长短交替）

## 输出格式
请严格按以下格式输出：

TITLE: [文章标题]
HOOK: [开头钩子类型]
STRUCTURE: [结构类型]
TONE: [语气风格]
TAGS: [5-8个标签，用逗号分隔]
IMAGE_DESC: [推荐首图描述，用于AI生成]

---

[正文内容，1000-1500字]"""


def build_user_prompt(book_content_summary, topic, angle):
    """构建用户提示词"""
    prompt = f"""请为「仙宝心灵成长」公众号写一篇文章。

## 主题
关于《{topic}》的深度解读

## 书中相关内容
{book_content_summary}

## 要求
- 以{angle["name"]}的角度切入
- 加入现代生活的真实案例
- 语言温暖不说教
- 结尾给出可操作的练习
"""
    return prompt


def call_deepseek(system_prompt, user_prompt, api_key):
    """调用DeepSeek API生成文章"""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.8,
        "max_tokens": 4000,
    }

    r = requests.post(DEEPSEEK_URL, headers=headers, json=payload, timeout=120)
    r.raise_for_status()
    data = r.json()
    return data["choices"][0]["message"]["content"]


def parse_article(raw_text):
    """解析AI生成的文章，提取元数据和正文"""
    result = {
        "title": "",
        "hook": "",
        "structure": "",
        "tone": "",
        "tags": "",
        "image_desc": "",
        "content": "",
    }

    # 提取元数据
    patterns = {
        "title": r"TITLE:\s*(.+)",
        "hook": r"HOOK:\s*(.+)",
        "structure": r"STRUCTURE:\s*(.+)",
        "tone": r"TONE:\s*(.+)",
        "tags": r"TAGS:\s*(.+)",
        "image_desc": r"IMAGE_DESC:\s*(.+)",
    }

    for key, pattern in patterns.items():
        match = re.search(pattern, raw_text)
        if match:
            result[key] = match.group(1).strip()

    # 提取正文（--- 之后的内容）
    parts = raw_text.split("---", 1)
    if len(parts) > 1:
        result["content"] = parts[1].strip()
    else:
        # 如果没有分隔符，尝试去掉元数据部分
        lines = raw_text.split("\n")
        content_lines = []
        found_end = False
        for line in lines:
            if found_end:
                content_lines.append(line)
            elif line.strip() == "" and content_lines:
                found_end = True
        result["content"] = "\n".join(content_lines) if content_lines else raw_text

    return result


def save_markdown(article, book_name, topic):
    """保存为Markdown文件"""
    ARTICLES_DIR.mkdir(parents=True, exist_ok=True)

    # 生成文件名
    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_topic = re.sub(r'[^\w\u4e00-\u9fff]', '_', topic)[:20]
    filename = f"{date_str}_{safe_topic}.md"

    filepath = ARTICLES_DIR / filename

    md_content = f"""# {article['title']}

> 📖 书目: 《{book_name}》
> 🎯 话题: {topic}
> 🪝 钩子: {article['hook']}
> 📐 结构: {article['structure']}
> 🎨 风格: {article['tone']}
> 🏷️ 标签: {article['tags']}
> 🖼️ 首图: {article['image_desc']}
> 📅 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}

---

{article['content']}

---

*想看完整精读？访问 lingxiu.xianbao.online*
"""

    filepath.write_text(md_content, encoding="utf-8")
    print(f"  ✅ Markdown已保存: {filepath}")
    return filepath, filename


def markdown_to_wechat_html(md_content, title, tags):
    """将Markdown转换为公众号HTML（图片base64内嵌）"""
    # 简单的Markdown转HTML
    html_body = md_content

    # 处理标题
    html_body = re.sub(r'^### (.+)$', r'<h3 style="font-size:18px;color:#333;margin:20px 0 10px;font-weight:bold;">\1</h3>', html_body, flags=re.MULTILINE)
    html_body = re.sub(r'^## (.+)$', r'<h2 style="font-size:20px;color:#333;margin:25px 0 12px;font-weight:bold;">\1</h2>', html_body, flags=re.MULTILINE)
    html_body = re.sub(r'^# (.+)$', r'<h1 style="font-size:24px;color:#333;margin:0 0 15px;font-weight:bold;">\1</h1>', html_body, flags=re.MULTILINE)

    # 处理加粗
    html_body = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html_body)

    # 处理引用
    html_body = re.sub(r'^> (.+)$', r'<blockquote style="border-left:3px solid #ddd;padding:8px 15px;margin:10px 0;color:#666;background:#f9f9f9;">\1</blockquote>', html_body, flags=re.MULTILINE)

    # 处理列表
    html_body = re.sub(r'^- (.+)$', r'<li style="margin:5px 0;">\1</li>', html_body, flags=re.MULTILINE)

    # 处理分割线
    html_body = re.sub(r'^---+$', r'<hr style="border:none;border-top:1px solid #eee;margin:20px 0;">', html_body, flags=re.MULTILINE)

    # 处理段落
    lines = html_body.split('\n')
    processed_lines = []
    for line in lines:
        line = line.strip()
        if not line:
            processed_lines.append('')
        elif line.startswith('<h') or line.startswith('<blockquote') or line.startswith('<li') or line.startswith('<hr'):
            processed_lines.append(line)
        elif line.startswith('*') and line.endswith('*') and not line.startswith('**'):
            # 斜体
            text = line.strip('*')
            processed_lines.append(f'<p style="margin:10px 0;line-height:1.8;color:#666;font-style:italic;text-align:center;">{text}</p>')
        else:
            processed_lines.append(f'<p style="margin:10px 0;line-height:1.8;color:#333;">{line}</p>')

    html_body = '\n'.join(processed_lines)

    # 构建完整HTML
    tags_html = ""
    if tags:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        tags_html = '<div style="margin:20px 0;">'
        for tag in tag_list:
            tags_html += f'<span style="display:inline-block;padding:3px 10px;margin:3px;background:#f0f0f0;border-radius:15px;font-size:13px;color:#666;">#{tag}</span>'
        tags_html += '</div>'

    full_html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
</head>
<body style="max-width:677px;margin:0 auto;padding:20px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Hiragino Sans GB','Microsoft YaHei',sans-serif;">
<div style="padding:15px 0;">
{html_body}
{tags_html}
<div style="margin-top:30px;padding-top:15px;border-top:1px solid #eee;text-align:center;">
<p style="font-size:13px;color:#999;">—— 仙宝心灵成长 ——</p>
<p style="font-size:12px;color:#bbb;">想看完整精读？访问 lingxiu.xianbao.online</p>
</div>
</div>
</body>
</html>"""

    return full_html


def save_html(html_content, filename):
    """保存HTML文件"""
    html_path = ARTICLES_DIR / filename.replace(".md", ".html")
    html_path.write_text(html_content, encoding="utf-8")
    print(f"  ✅ HTML已保存: {html_path}")
    return html_path


def send_feishu_notification(title, summary, book_name, topic, env):
    """发送飞书通知"""
    app_id = env.get("FEISHU_APP_ID")
    app_secret = env.get("FEISHU_APP_SECRET")

    if not app_id or not app_secret:
        print("  ⚠️ 飞书配置不完整，跳过通知")
        return False

    # 获取tenant_access_token
    try:
        r = requests.post(
            FEISHU_TOKEN_URL,
            json={"app_id": app_id, "app_secret": app_secret},
            timeout=10,
        )
        r.raise_for_status()
        token_data = r.json()
        if token_data.get("code") != 0:
            print(f"  ⚠️ 获取飞书token失败: {token_data}")
            return False
        token = token_data["tenant_access_token"]
    except Exception as e:
        print(f"  ⚠️ 获取飞书token异常: {e}")
        return False

    # 构建消息卡片
    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"📝 新文章已生成"},
            "template": "turquoise",
        },
        "elements": [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**标题**: {title}\n**书目**: 《{book_name}》\n**话题**: {topic}\n**摘要**: {summary[:200]}...",
                },
            },
            {"tag": "hr"},
            {
                "tag": "note",
                "elements": [
                    {
                        "tag": "plain_text",
                        "content": f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')} | 点击查看详情",
                    }
                ],
            },
        ],
    }

    # 发送消息
    try:
        r = requests.post(
            FEISHU_MSG_URL,
            headers={"Authorization": f"Bearer {token}"},
            params={"receive_id_type": "open_id"},
            json={
                "receive_id": FEISHU_USER_OPEN_ID,
                "msg_type": "interactive",
                "content": json.dumps(card),
            },
            timeout=10,
        )
        r.raise_for_status()
        result = r.json()
        if result.get("code") == 0:
            print("  ✅ 飞书通知已发送")
            return True
        else:
            print(f"  ⚠️ 飞书通知发送失败: {result}")
            return False
    except Exception as e:
        print(f"  ⚠️ 飞书通知发送异常: {e}")
        return False


def save_article_metadata(article, book_name, topic, angle, structure, tone, hook, scenario, md_filename):
    """保存文章元数据（供Web应用读取）"""
    meta_path = ARTICLES_DIR / md_filename.replace(".md", ".json")

    meta = {
        "id": md_filename.replace(".md", ""),
        "title": article["title"],
        "book": book_name,
        "topic": topic,
        "angle": angle["name"],
        "structure": structure[1],
        "tone": tone[0],
        "hook": hook[0],
        "scenario": scenario,
        "tags": article["tags"],
        "image_desc": article["image_desc"],
        "status": "pending",
        "created_at": datetime.now().isoformat(),
        "md_file": md_filename,
        "html_file": md_filename.replace(".md", ".html"),
        "summary": article["content"][:300] + "...",
    }

    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  ✅ 元数据已保存: {meta_path}")
    return meta_path



DASHSCOPE_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text2image/image-synthesis"
DASHSCOPE_TASK_URL = "https://dashscope.aliyuncs.com/api/v1/tasks/"

def generate_image(prompt, size="1280*720", api_key=None):
    """调用百炼API生成图片，返回图片数据"""
    if not api_key:
        return None
    try:
        r = requests.post(DASHSCOPE_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "X-DashScope-Async": "enable"
            },
            json={
                "model": "wanx2.1-t2i-turbo",
                "input": {"prompt": prompt},
                "parameters": {"size": size, "n": 1}
            },
            timeout=30
        )
        if r.status_code != 200:
            print(f"  warn: image request failed: {r.status_code}")
            return None
        task_id = r.json()["output"]["task_id"]
        for attempt in range(15):
            time.sleep(5)
            result = requests.get(
                f"{DASHSCOPE_TASK_URL}{task_id}",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=10
            ).json()
            status = result["output"]["task_status"]
            if status == "SUCCEEDED":
                url = result["output"]["results"][0]["url"]
                return requests.get(url, timeout=30).content
            elif status == "FAILED":
                print(f"  warn: image gen failed: {result.get('output', {}).get('message', 'unknown')}")
                return None
        print("  warn: image gen timeout")
        return None
    except Exception as e:
        print(f"  warn: image gen error: {e}")
        return None


def generate_article_images(article, article_dir, env):
    """为文章生成封面图和文中配图"""
    api_key = env.get("DASHSCOPE_API_KEY")
    if not api_key:
        print("  warn: no DASHSCOPE_API_KEY, skip image gen")
        return []
    
    images = []
    title = article.get('title', 'spiritual growth')
    
    # 封面图 (1280x720)
    cover_prompt = f"Beautiful illustration for article: {title}, warm golden and purple tones, dreamy atmosphere, soft light rays, minimalist digital art, landscape composition"
    print("  Generating cover image...")
    cover_data = generate_image(cover_prompt, "1280*720", api_key)
    if cover_data:
        cover_path = article_dir / "cover-raw.png"
        cover_path.write_bytes(cover_data)
        images.append(("cover", str(cover_path)))
        print(f"  Cover saved: {cover_path.name}")
        # 裁剪为900x383
        try:
            from PIL import Image
            import io
            img = Image.open(io.BytesIO(cover_data))
            tw, th = 900, 383
            ratio = tw / th
            cur = img.width / img.height
            if cur < ratio:
                nh = int(img.width / ratio)
                t = (img.height - nh) // 2
                img_c = img.crop((0, t, img.width, t + nh))
            else:
                nw = int(img.height * ratio)
                l = (img.width - nw) // 2
                img_c = img.crop((l, 0, l + nw, img.height))
            img_f = img_c.resize((tw, th), Image.LANCZOS)
            wechat_path = article_dir / "cover-wechat.png"
            img_f.save(wechat_path, "PNG")
            images.append(("cover-wechat", str(wechat_path)))
            print(f"  WeChat cover saved: {wechat_path.name} ({tw}x{th})")
        except Exception as e:
            print(f"  warn: crop failed: {e}")
    
    # 文中配图 (1024x1024)
    art1_prompt = "Serene illustration about inner peace and mindfulness, soft purple and gold colors, zen atmosphere, meditation concept, minimalist digital art"
    print("  Generating article image 1...")
    art1_data = generate_image(art1_prompt, "1024*1024", api_key)
    if art1_data:
        art1_path = article_dir / "article-1.png"
        art1_path.write_bytes(art1_data)
        images.append(("article-1", str(art1_path)))
        print(f"  Article image 1 saved: {art1_path.name}")
    
    return images

def main():
    print("=" * 60)
    print(f"🚀 公众号文章生成Agent - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 1. 加载配置
    env = load_env()
    wheel = load_content_wheel()
    api_key = env.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("❌ 缺少 DEEPSEEK_API_KEY")
        return

    # 2. 选材
    print("\n📚 选材中...")
    book, wheel = select_book(wheel)
    print(f"  书目: 《{book['name']}》 (ID: {book['id']})")

    category, topic, wheel = select_theme(wheel)
    print(f"  话题: {topic} (分类: {category['name']})")

    angle, wheel = select_angle(wheel)
    print(f"  角度: {angle['name']} - {angle['desc']}")

    scenario = select_scenario(wheel)
    print(f"  场景: {scenario}")

    hook = select_hook()
    print(f"  钩子: {hook[0]}")

    structure = select_structure()
    print(f"  结构: {structure[1]}")

    tone = select_tone()
    print(f"  风格: {tone[0]}")

    # 保存轮盘状态
    save_content_wheel(wheel)

    # 3. 获取书中内容
    print("\n📖 获取书中内容...")
    book_content = {"categories": [], "themes": {}}
    if book["id"] > 0:
        book_content = fetch_book_content(book["id"])
        print(f"  获取到 {len(book_content['categories'])} 个分类")

        # 获取一个主题详情作为参考
        theme_detail = None
        for cat_id, themes in book_content["themes"].items():
            if themes:
                theme_detail = fetch_theme_detail(book["id"], themes[0].get("id"))
                break
        if theme_detail:
            print(f"  获取到主题详情: {theme_detail.get('title', '未知')}")
    else:
        print("  ⚠️ 书目ID为0，跳过API获取（使用通用内容）")

    # 构建内容摘要
    content_summary = f"主题: {topic}\n分类: {category['name']}\n"
    if book_content.get("categories"):
        content_summary += "书中相关分类: " + ", ".join(
            [c.get("name", str(c.get("id", ""))) for c in book_content["categories"][:5]]
        ) + "\n"

    # 4. 调用DeepSeek生成文章
    print("\n🤖 调用DeepSeek生成文章...")
    system_prompt = build_system_prompt(structure, tone, hook, angle, scenario, book["name"], topic)
    user_prompt = build_user_prompt(content_summary, topic, angle)

    try:
        raw_text = call_deepseek(system_prompt, user_prompt, api_key)
        print(f"  ✅ 文章生成成功 ({len(raw_text)} 字符)")
    except Exception as e:
        print(f"  ❌ DeepSeek调用失败: {e}")
        return

    # 5. 解析文章
    print("\n📝 解析文章...")
    article = parse_article(raw_text)
    print(f"  标题: {article['title']}")
    print(f"  正文长度: {len(article['content'])} 字符")

    # 6. 保存文件
    print("\n💾 保存文件...")
    md_path, md_filename = save_markdown(article, book["name"], topic)

    # 保存HTML
    html_content = markdown_to_wechat_html(article["content"], article["title"], article["tags"])
    save_html(html_content, md_filename)

    # 保存元数据
    save_article_metadata(article, book["name"], topic, angle, structure, tone, hook, scenario, md_filename)


    # 7. 生成配图
    print("\nGenerating images...")
    img_dir = ARTICLES_DIR / md_filename.replace(".md", "")
    img_dir.mkdir(exist_ok=True)
    images = generate_article_images(article, img_dir, env)

    # 8. 发送飞书通知
    print("\n📤 发送飞书通知...")
    send_feishu_notification(article["title"], article["content"][:300], book["name"], topic, env)

    print("\n" + "=" * 60)
    print("✅ 文章生成完成！")
    print(f"  📄 Markdown: {md_path}")
    print(f"  🌐 HTML: {ARTICLES_DIR / md_filename.replace('.md', '.html')}")
    print("=" * 60)


if __name__ == "__main__":
    main()
