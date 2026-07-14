module.exports = {
  apps: [
    {
      name: "wechat-agent-web",
      script: "python3",
      args: "app.py",
      cwd: "/var/www/wechat-agent",
      env: {
        PYTHONUNBUFFERED: "1"
      },
      max_restarts: 5,
      restart_delay: 3000
    }
  ]
};
