# دليل تشغيل البوت على السيرفر (لـ Claude Code على جهاز عبدالرحمن)

هذا الملف مكتوب لـ Claude Code اللي يشتغل على جهاز المستخدم، لأن الجلسة السحابية اللي بنت البوت ما تقدر توصل للسيرفر.
المستخدم مو مبرمج: اشرح له بالعربي وبخطوات قصيرة، واطلب منه بس اللي تحتاجه.

## المعطيات
| الشي | القيمة |
|---|---|
| المستودع | `roundtripco/tiktok`، الفرع `claude/beautiful-wozniak-0ylwtv`، المجلد `aqar-bot/` |
| السيرفر | `187.127.84.160` (عليه خدمة ثانية على المنفذ 8080 لبروكسي Pexels، **لا تلمسها**) |
| البوت | `@AqarOfficeBot` |
| رقم المدير في تيليجرام | `6485022253` |
| منفذ لوحة التحكم | `8081` |

**أشياء تطلبها من المستخدم وقت الحاجة (لا تكتبها في أي ملف داخل المستودع):**
- طريقة الدخول للسيرفر (اسم المستخدم وكلمة السر أو مفتاح SSH)
- توكن البوت من @BotFather

## الخطوات

### ١. جهّز الكود على الجهاز
```bash
git clone https://github.com/roundtripco/tiktok.git && cd tiktok
git checkout claude/beautiful-wozniak-0ylwtv
```

### ٢. افحص السيرفر قبل أي تغيير
```bash
ssh <user>@187.127.84.160 'cat /etc/os-release | head -3; free -h; df -h /; ss -ltnp | grep -E ":(8080|8081)\b"; ufw status 2>/dev/null | head -5'
```
- لازم يكون Ubuntu أو Debian (سكربت التثبيت يستخدم `apt`).
- المنفذ 8081 لازم يكون فاضي. إذا مستخدم، اختر منفذ ثاني وغيّره في `DASHBOARD_PORT` و`DASHBOARD_URL`.
- الذاكرة: Chromium يحتاج تقريباً ٣٠٠–٥٠٠ ميقا وقت تجهيز البطاقات.

### ٣. انسخ الكود للسيرفر وثبّته
```bash
rsync -az --delete --exclude data --exclude .env --exclude samples --exclude marketing --exclude site \
  aqar-bot/ <user>@187.127.84.160:~/aqar-bot-src/
ssh <user>@187.127.84.160 'cd ~/aqar-bot-src && sudo bash deploy/install.sh'
```
السكربت ينشئ مستخدم `aqarbot`، ويثبّت Python وChromium في `/opt/aqar-bot`، ويسجّل خدمة `aqarbot` في systemd.

### ٤. الإعدادات
عدّل `/opt/aqar-bot/.env` على السيرفر (اطلب التوكن من المستخدم والصقه مباشرة في الملف):
```
BOT_TOKEN=<التوكن>
ADMIN_IDS=6485022253
SERVICE_NAME=مساعد المكتب العقاري
UPAY_LINK=
PRICE_KWD=12
TRIAL_DAYS=14
REMINDER_HOUR=9
DASHBOARD_URL=http://187.127.84.160:8081
DASHBOARD_PORT=8081
```
`UPAY_LINK` يبقى فاضي: روابط UPay تنتهي بعد ٢٤ ساعة، فالمكتب يطلب الرابط والمدير يرسله من البوت أو اللوحة.
بعدها: `sudo chown aqarbot:aqarbot /opt/aqar-bot/.env && sudo chmod 600 /opt/aqar-bot/.env`

### ٥. افتح منفذ اللوحة
```bash
sudo ufw allow 8081/tcp     # إذا ufw مفعّل
```
إذا شركة الاستضافة عندها جدار حماية في لوحتها (مثل Hostinger)، افتح المنفذ 8081 هناك بعد.

### ٦. شغّل وتأكد
```bash
sudo systemctl restart aqarbot
sudo journalctl -u aqarbot -n 50 --no-pager
```
لازم يطلع في السجل «لوحة التحكم شغالة على المنفذ 8081» وبدون أخطاء.

**تجربة مع المستخدم:**
1. يفتح @AqarOfficeBot ويضغط Start، ويسجّل مكتب تجريبي.
2. يجرب «🏠 بطاقة عقار» بصورة وحدة، ويتأكد إن البطاقة توصله.
3. يكتب `/dashboard` ويفتح الرابط من المتصفح، ويتأكد إن المكتب التجريبي يطلع في اللوحة.

## التحديث لاحقاً
```bash
cd tiktok && git pull
rsync -az --delete --exclude data --exclude .env --exclude samples --exclude marketing --exclude site \
  aqar-bot/ <user>@187.127.84.160:~/aqar-bot-src/
ssh <user>@187.127.84.160 'sudo rsync -a --delete --exclude data --exclude .env --exclude .venv ~/aqar-bot-src/ /opt/aqar-bot/ \
  && sudo /opt/aqar-bot/.venv/bin/pip install -q -r /opt/aqar-bot/requirements.txt \
  && sudo chown -R aqarbot:aqarbot /opt/aqar-bot && sudo systemctl restart aqarbot'
```

## النسخ الاحتياطي
كل البيانات في `/opt/aqar-bot/data/` (قاعدة البيانات `aqarbot.db` والشعارات). انسخها دورياً:
```bash
ssh <user>@187.127.84.160 'sudo tar czf - -C /opt/aqar-bot data' > aqarbot-backup-$(date +%F).tgz
```

## إذا صار خطأ
- `journalctl -u aqarbot -f` يعرض السجل مباشرة.
- خطأ Chromium (مكتبات ناقصة): `sudo /opt/aqar-bot/.venv/bin/playwright install-deps chromium`
- البوت ما يرد: تأكد إن ما فيه نسخة ثانية من البوت شغالة بنفس التوكن (تيليجرام يسمح بنسخة وحدة بس).
