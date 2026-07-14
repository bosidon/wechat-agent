#!/usr/bin/env python3
"""
公众号文章管理后台 - Flask Web应用
端口: 3010
"""

import json
import os
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template_string, jsonify, request, redirect, url_for

app = Flask(__name__)

BASE_DIR = Path(__file__).parent
ARTICLES_DIR = BASE_DIR / "articles"
ARTICLES_DIR.mkdir(parents=True, exist_ok=True)


def load_all_articles():
    """加载所有文章的元数据"""
    articles = []
    for meta_file in sorted(ARTICLES_DIR.glob("*.json"), reverse=True):
        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                meta = json.load(f)
            articles.append(meta)
        except Exception as e:
            print(f"读取 {meta_file} 失败: {e}")
    return articles


def get_article(article_id):
    """获取单篇文章的元数据"""
    meta_path = ARTICLES_DIR / f"{article_id}.json"
    if meta_path.exists():
        with open(meta_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def get_article_html(article_id):
    """获取文章HTML内容"""
    html_path = ARTICLES_DIR / f"{article_id}.html"
    if html_path.exists():
        return html_path.read_text(encoding="utf-8")
    return None


def get_article_md(article_id):
    """获取文章Markdown内容"""
    md_path = ARTICLES_DIR / f"{article_id}.md"
    if md_path.exists():
        return md_path.read_text(encoding="utf-8")
    return None


# ============================================================
# HTML模板
# ============================================================

LIST_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>仙宝心灵成长 - 文章管理</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', sans-serif; background: #f5f5f5; color: #333; }
.header { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px 30px; }
.header h1 { font-size: 22px; font-weight: 600; }
.header p { font-size: 14px; opacity: 0.8; margin-top: 5px; }
.container { max-width: 1000px; margin: 20px auto; padding: 0 20px; }
.stats { display: flex; gap: 15px; margin-bottom: 20px; }
.stat-card { background: white; border-radius: 10px; padding: 15px 20px; flex: 1; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
.stat-card .num { font-size: 28px; font-weight: 700; color: #667eea; }
.stat-card .label { font-size: 13px; color: #999; margin-top: 3px; }
.table-wrap { background: white; border-radius: 10px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); overflow: hidden; }
table { width: 100%; border-collapse: collapse; }
th { background: #fafafa; padding: 12px 15px; text-align: left; font-size: 13px; color: #999; font-weight: 500; border-bottom: 1px solid #eee; }
td { padding: 12px 15px; border-bottom: 1px solid #f5f5f5; font-size: 14px; }
tr:hover { background: #f9f9ff; }
.status { display: inline-block; padding: 3px 10px; border-radius: 12px; font-size: 12px; font-weight: 500; }
.status-pending { background: #fff3e0; color: #e65100; }
.status-approved { background: #e8f5e9; color: #2e7d32; }
.status-published { background: #e3f2fd; color: #1565c0; }
.btn { display: inline-block; padding: 5px 12px; border-radius: 6px; font-size: 12px; text-decoration: none; cursor: pointer; border: none; margin-right: 5px; }
.btn-view { background: #667eea; color: white; }
.btn-approve { background: #4caf50; color: white; }
.btn-publish { background: #2196f3; color: white; }
.btn-pending { background: #ff9800; color: white; }
.empty { text-align: center; padding: 60px 20px; color: #999; }
.empty p { margin: 5px 0; }
</style>
</head>
<body>
<div class="header">
    <h1>📝 仙宝心灵成长 - 文章管理</h1>
    <p>公众号文章生成Agent后台</p>
</div>
<div class="container">
    <div class="stats">
        <div class="stat-card">
            <div class="num">{{ total }}</div>
            <div class="label">总文章数</div>
        </div>
        <div class="stat-card">
            <div class="num">{{ pending }}</div>
            <div class="label">待审核</div>
        </div>
        <div class="stat-card">
            <div class="num">{{ approved }}</div>
            <div class="label">已审核</div>
        </div>
        <div class="stat-card">
            <div class="num">{{ published }}</div>
            <div class="label">已发布</div>
        </div>
    </div>
    <div class="table-wrap">
        {% if articles %}
        <table>
            <thead>
                <tr>
                    <th>标题</th>
                    <th>书目</th>
                    <th>话题</th>
                    <th>状态</th>
                    <th>生成时间</th>
                    <th>操作</th>
                </tr>
            </thead>
            <tbody>
            {% for a in articles %}
                <tr>
                    <td><a href="/article/{{ a.id }}" style="color:#667eea;text-decoration:none;font-weight:500;">{{ a.title }}</a></td>
                    <td>{{ a.book }}</td>
                    <td>{{ a.topic }}</td>
                    <td><span class="status status-{{ a.status }}">{{ status_map[a.status] }}</span></td>
                    <td style="color:#999;font-size:13px;">{{ a.created_at[:16] }}</td>
                    <td>
                        <a href="/article/{{ a.id }}" class="btn btn-view">预览</a>
                        {% if a.status == 'pending' %}
                        <button class="btn btn-approve" onclick="updateStatus('{{ a.id }}', 'approved')">通过</button>
                        {% elif a.status == 'approved' %}
                        <button class="btn btn-publish" onclick="updateStatus('{{ a.id }}', 'published')">发布</button>
                        <button class="btn btn-pending" onclick="updateStatus('{{ a.id }}', 'pending')">退回</button>
                        {% elif a.status == 'published' %}
                        <button class="btn btn-pending" onclick="updateStatus('{{ a.id }}', 'approved')">撤回</button>
                        {% endif %}
                    </td>
                </tr>
            {% endfor %}
            </tbody>
        </table>
        {% else %}
        <div class="empty">
            <p style="font-size:40px;">📭</p>
            <p>还没有文章</p>
            <p style="font-size:13px;">运行 python3 generate.py 生成第一篇文章</p>
        </div>
        {% endif %}
    </div>
</div>
<script>
function updateStatus(id, status) {
    fetch('/api/article/' + id + '/status', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({status: status})
    }).then(r => r.json()).then(data => {
        if (data.success) location.reload();
        else alert('更新失败: ' + (data.error || '未知错误'));
    });
}
</script>
</body>
</html>
"""


ARTICLE_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{ title }} - 仙宝心灵成长</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', sans-serif; background: #f5f5f5; }
.topbar { background: white; padding: 12px 30px; border-bottom: 1px solid #eee; display: flex; align-items: center; justify-content: space-between; position: sticky; top: 0; z-index: 10; }
.topbar a { color: #667eea; text-decoration: none; font-size: 14px; }
.topbar .title { font-size: 15px; font-weight: 600; color: #333; }
.meta-bar { max-width: 677px; margin: 20px auto; padding: 15px 20px; background: white; border-radius: 10px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
.meta-bar .row { display: flex; gap: 20px; flex-wrap: wrap; font-size: 13px; color: #666; }
.meta-bar .item { display: flex; align-items: center; gap: 5px; }
.meta-bar .label { color: #999; }
.article-frame { max-width: 677px; margin: 15px auto 40px; background: white; border-radius: 10px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); overflow: hidden; }
.article-frame iframe { width: 100%; border: none; min-height: 800px; }
.actions { max-width: 677px; margin: 0 auto 40px; display: flex; gap: 10px; justify-content: center; }
.actions .btn { padding: 10px 25px; border-radius: 8px; font-size: 14px; cursor: pointer; border: none; font-weight: 500; }
.actions .btn-approve { background: #4caf50; color: white; }
.actions .btn-publish { background: #2196f3; color: white; }
.actions .btn-pending { background: #ff9800; color: white; }
</style>
</head>
<body>
<div class="topbar">
    <a href="/">← 返回列表</a>
    <span class="title">{{ title }}</span>
    <span></span>
</div>
<div class="meta-bar">
    <div class="row">
        <div class="item"><span class="label">📖 书目:</span> 《{{ article.book }}》</div>
        <div class="item"><span class="label">🎯 话题:</span> {{ article.topic }}</div>
        <div class="item"><span class="label">📐 结构:</span> {{ article.structure }}</div>
        <div class="item"><span class="label">🎨 风格:</span> {{ article.tone }}</div>
        <div class="item"><span class="label">🪝 钩子:</span> {{ article.hook }}</div>
        <div class="item"><span class="label">🏷️ 标签:</span> {{ article.tags }}</div>
    </div>
</div>
<div class="article-frame">
    <iframe src="/raw-html/{{ article.id }}" id="articleFrame"></iframe>
</div>
<div class="actions">
    {% if article.status == 'pending' %}
    <button class="btn btn-approve" onclick="updateStatus('approved')">✅ 通过审核</button>
    {% elif article.status == 'approved' %}
    <button class="btn btn-publish" onclick="updateStatus('published')">🚀 发布</button>
    <button class="btn btn-pending" onclick="updateStatus('pending')">↩ 退回</button>
    {% elif article.status == 'published' %}
    <button class="btn btn-pending" onclick="updateStatus('approved')">撤回</button>
    {% endif %}
</div>
<script>
function updateStatus(status) {
    fetch('/api/article/{{ article.id }}/status', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({status: status})
    }).then(r => r.json()).then(data => {
        if (data.success) location.reload();
        else alert('更新失败');
    });
}
// 自动调整iframe高度
document.getElementById('articleFrame').onload = function() {
    try {
        this.style.height = this.contentWindow.document.body.scrollHeight + 40 + 'px';
    } catch(e) {}
};
</script>
</body>
</html>
"""


# ============================================================
# 路由
# ============================================================

@app.route("/")
def index():
    """文章列表"""
    articles = load_all_articles()
    status_map = {"pending": "待审核", "approved": "已审核", "published": "已发布"}
    return render_template_string(
        LIST_TEMPLATE,
        articles=articles,
        total=len(articles),
        pending=sum(1 for a in articles if a["status"] == "pending"),
        approved=sum(1 for a in articles if a["status"] == "approved"),
        published=sum(1 for a in articles if a["status"] == "published"),
        status_map=status_map,
    )


@app.route("/article/<article_id>")
def article_preview(article_id):
    """文章预览"""
    article = get_article(article_id)
    if not article:
        return "文章不存在", 404
    return render_template_string(ARTICLE_TEMPLATE, article=article, title=article["title"])


@app.route("/raw-html/<article_id>")
def raw_html(article_id):
    """返回原始HTML（用于iframe）"""
    html = get_article_html(article_id)
    if not html:
        return "HTML文件不存在", 404
    return html, 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/api/article/<article_id>")
def api_article(article_id):
    """文章JSON数据"""
    article = get_article(article_id)
    if not article:
        return jsonify({"error": "文章不存在"}), 404
    return jsonify(article)


@app.route("/api/article/<article_id>/status", methods=["POST"])
def api_update_status(article_id):
    """更新文章状态"""
    article = get_article(article_id)
    if not article:
        return jsonify({"error": "文章不存在"}), 404

    data = request.get_json()
    new_status = data.get("status")
    if new_status not in ("pending", "approved", "published"):
        return jsonify({"error": "无效状态"}), 400

    article["status"] = new_status
    article["updated_at"] = datetime.now().isoformat()

    meta_path = ARTICLES_DIR / f"{article_id}.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(article, f, ensure_ascii=False, indent=2)

    return jsonify({"success": True, "status": new_status})


@app.route("/api/articles")
def api_articles():
    """所有文章列表JSON"""
    return jsonify(load_all_articles())


@app.route("/health")
def health():
    """健康检查"""
    return jsonify({"status": "ok", "service": "wechat-agent", "articles": len(load_all_articles())})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3010, debug=False)
