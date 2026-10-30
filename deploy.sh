#!/bin/bash
# ==============================================================================
# ⚔️ Скрипт автоматического деплоя бота «Тёмный Век RPG» для VPS (Ubuntu/Debian)
# ==============================================================================
set -e

# Цвета для красивого вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}============================================================${NC}"
echo -e "${YELLOW}  ⚔️  НАЧАЛО ДЕПЛОЯ: ТЁМНЫЙ ВЕК RPG (Telegram Bot)        ${NC}"
echo -e "${BLUE}============================================================${NC}"

# 1. Проверка прав root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}❌ Запустите скрипт с правами root: sudo bash deploy.sh${NC}"
    exit 1
fi

# 2. Настройка SWAP (файла подкачки 2 ГБ)
echo -e "\n${YELLOW}🧠 [1/6] Проверка и настройка Swap памяти...${NC}"
SWAP_TOTAL=$(free -m | awk '/Swap:/ {print $2}')

if [ "$SWAP_TOTAL" -lt 1000 ]; then
    echo -e "${BLUE}ℹ️ Swap отсутствует или меньше 1 ГБ. Создаем 2 ГБ Swap на SSD...${NC}"
    # Проверяем, существует ли уже неактивный swapfile
    if [ ! -f /swapfile ]; then
        fallocate -l 2G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048
    fi
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile

    # Добавляем в fstab если еще не добавлено
    if ! grep -q '/swapfile none swap' /etc/fstab; then
        echo '/swapfile none swap sw 0 0' >> /etc/fstab
    fi

    # Оптимизация работы со swap для SSD
    sysctl vm.swappiness=20 > /dev/null 2>&1 || true
    sysctl vm.vfs_cache_pressure=50 > /dev/null 2>&1 || true
    echo -e "${GREEN}✅ Swap файл на 2 ГБ успешно создан и активирован!${NC}"
else
    echo -e "${GREEN}✅ Swap уже настроен (${SWAP_TOTAL} МБ). Пропускаем.${NC}"
fi

# 3. Обновление пакетов и установка системных утилит
echo -e "\n${YELLOW}📦 [2/6] Установка системных зависимостей (Python 3, Git, venv)...${NC}"
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv git curl

# 4. Определение рабочей директории
INSTALL_DIR="/opt/noviybot"
echo -e "\n${YELLOW}📁 [3/6] Подготовка файлов проекта в ${INSTALL_DIR}...${NC}"

# Если скрипт запущен уже внутри склонированного репозитория
CURRENT_DIR=$(pwd)
if [ -f "$CURRENT_DIR/bot.py" ]; then
    INSTALL_DIR="$CURRENT_DIR"
    echo -e "${BLUE}ℹ️ Используем текущую директорию: ${INSTALL_DIR}${NC}"
else
    if [ ! -d "$INSTALL_DIR" ]; then
        git clone https://github.com/Myrzikbog/noviybot.git "$INSTALL_DIR"
    else
        echo -e "${BLUE}ℹ️ Директория существует, обновляем репозиторий...${NC}"
        cd "$INSTALL_DIR" && git pull origin main || true
    fi
fi

cd "$INSTALL_DIR"

# 5. Создание виртуального окружения Python
echo -e "\n${YELLOW}🐍 [4/6] Установка виртуального окружения и библиотек...${NC}"
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

./venv/bin/pip install --upgrade pip -q
./venv/bin/pip install -r requirements.txt -q
echo -e "${GREEN}✅ Зависимости успешно установлены.${NC}"

# 6. Проверка и настройка .env
echo -e "\n${YELLOW}🔑 [5/6] Проверка файла конфигурации (.env)...${NC}"
if [ ! -f ".env" ] || ! grep -q "BOT_TOKEN=" .env || grep -q "BOT_TOKEN=$" .env; then
    echo -e "${YELLOW}⚠️ Файл .env не настроен. Давайте введем ключи сейчас:${NC}"
    
    read -p "Введите Telegram BOT_TOKEN от @BotFather: " USER_BOT_TOKEN
    read -p "Введите GEMINI_API_KEY от Google AI Studio: " USER_GEMINI_KEY

    cat <<EOF > .env
BOT_TOKEN=${USER_BOT_TOKEN}
GEMINI_API_KEY=${USER_GEMINI_KEY}
GEMINI_MODEL=gemini-2.5-flash
EOF
    echo -e "${GREEN}✅ Файл .env успешно сохранен!${NC}"
else
    echo -e "${GREEN}✅ Файл .env уже существует и заполнен.${NC}"
fi

# 7. Настройка и запуск службы Systemd (Автозапуск 24/7)
echo -e "\n${YELLOW}⚙️  [6/6] Настройка автозапуска службы Systemd...${NC}"
SERVICE_FILE="/etc/systemd/system/darkage_bot.service"

cat <<EOF > "$SERVICE_FILE"
[Unit]
Description=Dark Age Telegram RPG Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${INSTALL_DIR}
ExecStart=${INSTALL_DIR}/venv/bin/python ${INSTALL_DIR}/bot.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable darkage_bot > /dev/null 2>&1
systemctl restart darkage_bot

echo -e "\n${BLUE}============================================================${NC}"
echo -e "${GREEN}🎉 ДЕПЛОЙ УСПЕШНО ЗАВЕРШЁН! БОТ РАБОТАЕТ В ФОНЕ (24/7)!${NC}"
echo -e "${BLUE}============================================================${NC}"
echo -e "Полезные команды:"
echo -e "  • Проверить статус:  ${YELLOW}systemctl status darkage_bot${NC}"
echo -e "  • Смотреть логи:     ${YELLOW}journalctl -u darkage_bot -f${NC}"
echo -e "  • Перезапустить:     ${YELLOW}systemctl restart darkage_bot${NC}"
echo -e "  • Остановить:        ${YELLOW}systemctl stop darkage_bot${NC}"
echo -e "============================================================\n"
