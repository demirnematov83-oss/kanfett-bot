# Kanfet Hisobi — Telegram bot o'rnatish yo'riqnomasi

## 1. Bot tokenini olish
1. Telegramda **@BotFather** ni toping, `/start` bosing.
2. `/newbot` yuboring, botga ism va username bering (username `bot` bilan tugashi kerak, masalan `KanfetHisobBot`).
3. BotFather sizga **token** beradi (masalan `123456:ABC-...`) — uni saqlab qo'ying, hech kimga bermang.

## 2. O'zingiz va xodimlaringizning Telegram ID raqamini oling
1. Telegramda **@userinfobot** ni toping, `/start` bosing.
2. U sizga ID raqamingizni yuboradi (masalan `123456789`).
3. Har bir xodimingiz ham shu botga yozib o'z ID raqamini sizga aytishi kerak.
4. Barcha ID raqamlarni yozib qo'ying — keyingi bosqichda kerak bo'ladi.

## 3. Kodni GitHub'ga joylashtirish
1. [github.com](https://github.com) da yangi repository yarating (masalan `kanfet-bot`), **Private** qilib qo'yishingiz mumkin.
2. Shu papkadagi 4 ta faylni (`bot.py`, `requirements.txt`, `Procfile`, `SETUP.md`) o'sha repoga yuklang ("Add file" → "Upload files").

## 4. Railway'da loyiha yaratish
1. [railway.app](https://railway.app) ga GitHub akkountingiz bilan kiring.
2. **New Project** → **Deploy from GitHub repo** → yuqorida yaratgan repongizni tanlang.
3. Railway avtomatik ravishda Python ekanini aniqlaydi va deploy qila boshlaydi (hozircha xato chiqishi mumkin — keyingi qadamda sozlaymiz).

## 5. Muhit o'zgaruvchilarini (Variables) qo'shish
Loyihangiz ichida **Variables** bo'limiga o'ting va quyidagilarni qo'shing:

| Nomi | Qiymati |
|---|---|
| `BOT_TOKEN` | BotFather bergan token |
| `ALLOWED_USER_IDS` | Barcha ruxsat etilgan ID'lar, vergul bilan: `123456789,987654321` |
| `DB_PATH` | `/data/kanfet.db` |

## 6. Doimiy xotira (Volume) qo'shish
Ma'lumotlar har deploy'da o'chib ketmasligi uchun:
1. Loyihangizda **+ New** → **Volume** ni tanlang.
2. **Mount path** sifatida `/data` deb yozing.
3. Saqlang.

## 7. Start Command tekshirish
1. Service → **Settings** → **Deploy** bo'limiga o'ting.
2. **Start Command** maydoniga `python bot.py` deb yozing (agar bo'sh bo'lsa).
3. **Redeploy** tugmasini bosing.

## 8. Sinab ko'ring
1. Bir necha daqiqa kuting (Railway "Deployed" deb ko'rsatadi).
2. Telegramda botingizning username'ini toping va `/start` yuboring.
3. Pastda chiqqan tugmalar orqali Kirim/Chiqim/Qoldiq/Tarixni sinab ko'ring.

---

### Eslatma
- `ALLOWED_USER_IDS` bo'sh qoldirilsa, bot **hammaga ochiq** bo'lib qoladi — buni tavsiya etilmaydi.
- Keyinchalik yangi xodim qo'shish uchun shunchaki uning ID raqamini `ALLOWED_USER_IDS` ga qo'shib, qayta deploy qilsangiz bo'ldi.
- Muammo bo'lsa, Railway loyihasidagi **Deployments → View Logs** orqali xatoni ko'rishingiz mumkin.
