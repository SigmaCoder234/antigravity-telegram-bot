#!/usr/bin/env bash

BOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="$BOT_DIR/data/bot.log"
SERVICE_NAME="telegram-bot"

mkdir -p "$BOT_DIR/data" "$BOT_DIR/workspace/uploads"

case "$1" in
  start)
    if systemctl is-enabled "$SERVICE_NAME" &>/dev/null; then
      echo "🚀 Запуск через systemd service..."
      systemctl start "$SERVICE_NAME"
      systemctl status "$SERVICE_NAME" --no-pager
    else
      echo "🚀 Запуск через systemctl enable & start..."
      systemctl enable --now "$SERVICE_NAME"
    fi
    ;;

  stop)
    echo "🛑 Остановка службы $SERVICE_NAME..."
    systemctl stop "$SERVICE_NAME"
    echo "✅ Бот остановлен."
    ;;

  restart)
    echo "🔄 Перезапуск службы $SERVICE_NAME..."
    systemctl restart "$SERVICE_NAME"
    sleep 1
    systemctl status "$SERVICE_NAME" --no-pager
    ;;

  status)
    systemctl status "$SERVICE_NAME" --no-pager
    ;;

  logs)
    journalctl -u "$SERVICE_NAME" -f -n 50
    ;;

  foreground)
    echo "⚡ Запуск бота в интерактивном режиме (остановите службу перед этим)..."
    systemctl stop "$SERVICE_NAME" 2>/dev/null || true
    exec python3 "$BOT_DIR/bot.py"
    ;;

  *)
    echo "Использование: $0 {start|stop|restart|status|logs|foreground}"
    exit 1
    ;;
esac
