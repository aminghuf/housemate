"""All user-facing text lives here as named constants (spec §9).

Persian for conversational text; Italian for the trash-category names
themselves, matching how they'd actually be read on collection day.
"""

# --- Onboarding / membership ---
NOT_A_CHANNEL_MEMBER = (
    "برای استفاده از این ربات باید عضو کانال خونه باشی. "
    "اول عضو کانال شو، بعد دوباره /start رو بزن."
)
NOT_A_CHANNEL_MEMBER_WITH_LINK = (
    "برای استفاده از این ربات باید عضو کانال خونه باشی.\n"
    "لینک عضویت: {invite_link}\n"
    "بعد از عضویت دوباره /start رو بزن."
)
WELCOME_REGISTERED = (
    "خوش اومدی {display_name}! ثبت‌نام شدی و می‌تونی از امکانات ربات استفاده کنی."
)
ACCESS_LOST_NOT_MEMBER = (
    "به نظر میاد دیگه عضو کانال خونه نیستی، برای همین دسترسی‌ت به ربات موقتاً قطع شد. "
    "اگه دوباره عضو شدی /start رو بزن."
)
PLEASE_START_FIRST = "اول باید /start رو بزنی."
NOT_ADMIN = "این دستور فقط برای ادمین‌هاست."

# --- Main menu ---
MENU_TRASH = "🗑️ نوبت زباله"
MENU_BILLS = "💸 صورتحساب‌ها"
MENU_SHOPPING = "🛒 لیست خرید"
MENU_CLEANING = "🧹 نوبت نظافت"
MENU_ADMIN = "⚙️ تنظیمات"

# --- Shared ---
NOT_YOUR_TURN = "این نوبت شما نیست"
ALREADY_HANDLED = "این قبلاً ثبت شده"
NOTHING_TO_SHOW = "چیزی برای نمایش نیست."
DONE_BUTTON_TOAST = "ثبت شد ✅"
NOT_YOUR_SHARE = "فقط سهم خودتون رو می‌تونید علامت بزنید"
CONFIRM_YES = "✅ تایید"
CONFIRM_CANCEL = "❌ لغو"
VOLUNTEER_NOTE = "\n🙋 نوبت {assigned_name} بود، ولی داوطلبانه انجام شد."
VOLUNTEER_INLINE_SUFFIX = " (🙋 به‌جای {assigned_name})"

# --- Trash duty (§5) ---
BTN_TRASH_DONE = "✅ انداختم دور"
BTN_TRASH_NOT_NEEDED = "❌ نیاز نبود / پر نشده هنوز"
TRASH_REMINDER = "🗑️ {mention} فردا نوبت زباله‌ته!\nنوع زباله فردا: <b>{trash_type}</b>\nیادت نره امشب ببریش."
TRASH_DONE_CONFIRMATION = "✅ زباله‌ی <b>{trash_type}</b> توسط {mention} انداخته شد.\n🕒 {timestamp}"
TRASH_SKIPPED_CONFIRMATION = "🔁 بازبینی شد — لازم نبود ({mention})\n🕒 {timestamp}"
TRASH_NO_COLLECTION_TODAY = "امروز یکشنبه‌ست و جمع‌آوری زباله نداریم."
TRASH_NOT_POSTED_YET = "یادآوری امروز هنوز پست نشده."
TRASH_NO_HOUSEMATES = "هنوز کسی توی چرخه‌ی نوبت زباله ثبت نشده."
TRASH_TODAY_STATUS_HEADER = "🗑️ وضعیت زباله‌ی امروز:"
TRASH_HISTORY_ENTRY = "{date} — {trash_type} — {assigned} — {status}"
TRASH_STATUS_PENDING = "⏳ در انتظار"
TRASH_STATUS_DONE = "✅ انجام شد"
TRASH_STATUS_SKIPPED = "🔁 لازم نبود"
TRASH_FORECAST_BUTTON = "📅 ۷ روز آینده"
TRASH_FORECAST_HEADER = "📅 پیش‌بینی نوبت زباله (۷ روز آینده):"
TRASH_FORECAST_LINE = "{date} ({trash_type}): {name}{marker}"
TRASH_FORECAST_NO_HOUSEMATES_LINE = "{date} ({trash_type}): کسی توی چرخه نیست"
TRASH_FORECAST_PROJECTED_MARK = " (پیش‌بینی)"
TRASH_FORECAST_FOOTNOTE = (
    "\n⚠️ مواردی که «پیش‌بینی» دارن قطعی نیستن — اگه یکی «نیاز نبود» بزنه، نوبت‌های بعدی جابه‌جا میشن."
)
TRASH_HISTORY_VOLUNTEER_SUFFIX = " (🙋 {doer})"

# --- Bills (§6) ---
BILLS_MENU_NEW = "➕ صورتحساب جدید"
BILLS_MENU_MINE = "📋 صورتحساب‌های من"
BILLS_MENU_HISTORY = "🗂️ تاریخچه"
BILLS_MENU_BALANCE = "⚖️ تراز حساب"
BILL_ASK_TITLE = "عنوان صورتحساب چیه؟"
BILL_ASK_DESCRIPTION = "توضیحات (اختیاری) بنویس، یا رد کن."
BILL_SKIP = "رد کردن / Skip"
BILL_ASK_AMOUNT = "مبلغ کل چقدره؟ (فقط عدد، مثلا 45.50)"
BILL_INVALID_AMOUNT = "مبلغ نامعتبره. یه عدد مثبت بفرست، مثلا 45.50"
BILL_CONFIRM = (
    "بررسی کن:\n"
    "📌 <b>{title}</b>\n"
    "{description_line}"
    "💰 مبلغ کل: {total}\n"
    "👤 سهم هرنفر (تقریبی): {per_person}\n"
    "تایید می‌کنی؟"
)
BILL_CANCELLED = "صورتحساب لغو شد."
BILL_CREATED = "صورتحساب ثبت شد و توی کانال پست شد."
BILL_HEADER = "💸 <b>{title}</b>"
BILL_TOTAL_LINE = "💰 مبلغ کل: {total}"
BILL_PER_PERSON_LINE = "👤 سهم هرنفر (تقریبی): {per_person}"
BILL_UNPAID_LABEL = "{name} — پرداخت نشده"
BILL_PAID_LABEL = "✅ {name}"
BILL_FULLY_SETTLED = "✅ تسویه شد"
BILL_MY_BILLS_HEADER = "📋 صورتحساب‌های پرداخت‌نشده‌ی تو:"
BILL_HISTORY_ENTRY = "#{id} {title} — {total} — {status}"
BILL_STATUS_SETTLED = "✅ تسویه شده"
BILL_STATUS_OPEN = "⏳ باز"
BALANCE_HEADER = "⚖️ تراز فعلی (چقدر هرکس بدهکاره):"
BALANCE_LINE = "{name}: {amount}"
BALANCE_NONE_OWED = "کسی به کسی بدهکار نیست 🎉"

# --- Shopping list (§7) ---
SHOPPING_ADD_BUTTON = "➕ اضافه کردن آیتم"
SHOPPING_ASK_TITLE = "چی می‌خوای اضافه کنی؟"
SHOPPING_ITEM_ADDED = "«{title}» به لیست اضافه شد."
SHOPPING_LIST_HEADER = "🛒 لیست خرید:"
SHOPPING_LIST_EMPTY = "🧺 لیست خرید خالیه"
SHOPPING_HISTORY_ENTRY = "{title} — خریداری شد توسط {buyer} ({date})"

# --- Cleaning turns (§8) ---
CLEANING_SECTION_KITCHEN = "🍳 آشپزخانه"
CLEANING_SECTION_HALL = "🛋️ هال"
CLEANING_SECTION_BATHROOM = "🚿 حمام"
BTN_CLEANING_DONE = "✅ تمیز کردم"
BTN_CLEANING_NOT_NEEDED = "➖ نیازی نبود"
CLEANING_HEADER = "🧹 نوبت نظافت این هفته:"
CLEANING_SECTION_PENDING_LINE = "{section}: {mention}"
CLEANING_SECTION_DONE_LINE = "{section}: ✅ {name} انجام داد ({timestamp})"
CLEANING_SECTION_SKIPPED_LINE = "{section}: ➖ لازم نبود ({name}, {timestamp})"
CLEANING_NO_HOUSEMATES = "هنوز کسی توی چرخه‌ی نوبت نظافت ثبت نشده."
CLEANING_THIS_WEEK_EMPTY = "هنوز نوبت این هفته اعلام نشده."
CLEANING_HISTORY_ENTRY = "{week} — {section} — {name} — {status}"
CLEANING_STATUS_PENDING = "⏳ در انتظار"
CLEANING_STATUS_DONE = "✅ انجام شد"
CLEANING_STATUS_SKIPPED = "➖ لازم نبود"
CLEANING_FORECAST_BUTTON = "📅 ۷ روز آینده"
CLEANING_FORECAST_HEADER = "📅 پیش‌بینی نوبت نظافت (۷ روز آینده):"
CLEANING_FORECAST_DATE_HEADER = "📆 {date}{marker}"
CLEANING_FORECAST_NOT_POSTED_MARK = " (هنوز پست نشده)"
CLEANING_FORECAST_SECTION_LINE = "   {section}: {name}"
CLEANING_FORECAST_NO_HOUSEMATES = "   کسی توی چرخه نیست"

# --- Admin (§10) ---
ADMIN_MENU_TEXT = (
    "⚙️ دستورات ادمین:\n"
    "/announce <متن> (یا بدون متن برای شروع مکالمه)\n"
    "/set_trash_reminder_time HH:MM\n"
    "/set_cleaning_reminder <weekday 0-6|mon..sun> HH:MM\n"
    "/trash_rotation [id1 id2 ...]\n"
    "/cleaning_rotation [id1 id2 ...]\n"
    "/setup_rotation id1 id2 ...\n"
    "/add_housemate <id> <name>\n"
    "/remove_housemate <id>"
)
ADMIN_INVALID_TIME = "فرمت ساعت درست نیست. مثال: 08:30"
ADMIN_INVALID_WEEKDAY = "روز هفته نامعتبره. از عدد 0 تا 6 (دوشنبه=0) یا mon..sun استفاده کن."
ADMIN_TRASH_TIME_SET = "⏰ ساعت یادآوری زباله شد: {time}"
ADMIN_CLEANING_REMINDER_SET = "⏰ یادآوری نظافت شد: {weekday} ساعت {time}"
ADMIN_ROTATION_EMPTY = "چرخه هنوز خالیه."
ADMIN_ROTATION_HEADER = "چرخه‌ی فعلی:"
ADMIN_ROTATION_LINE = "{position}. {name}"
ADMIN_ROTATION_MISMATCH = "لیست آیدی‌ها باید دقیقاً همون افرادی باشه که الان توی چرخه هستن، فقط با ترتیب جدید."
ADMIN_ROTATION_USAGE = "برای تغییر ترتیب، آیدی همه‌ی افراد رو با ترتیب جدید بفرست، مثلا:\n/trash_rotation 111 222 333"
ADMIN_ROTATION_REORDERED = "ترتیب چرخه به‌روزرسانی شد."
ADMIN_HOUSEMATE_USAGE = "استفاده: /add_housemate <telegram_id> <نام>"
ADMIN_HOUSEMATE_ADDED = "{name} به لیست هم‌خونه‌ای‌ها اضافه شد."
ADMIN_REMOVE_HOUSEMATE_USAGE = "استفاده: /remove_housemate <telegram_id>"
ADMIN_HOUSEMATE_REMOVED = "{name} از چرخه‌ها حذف شد (تاریخچه‌ش نگه داشته میشه)."
ADMIN_HOUSEMATE_NOT_FOUND = "همچین کسی پیدا نشد."
WEEKDAY_LABELS_FA = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه"]

ADMIN_ANNOUNCE_BUTTON = "📢 اعلامیه جدید"
ADMIN_ANNOUNCE_ASK_TEXT = "متن اعلامیه رو بفرست."
ADMIN_ANNOUNCE_PREVIEW = "📢 پیش‌نمایش اعلامیه:\n\n{text}\n\nپست بشه؟"
ADMIN_ANNOUNCE_CHANNEL_POST = "📢 <b>اعلامیه</b>\n\n{text}"
ADMIN_ANNOUNCE_CANCELLED = "اعلامیه لغو شد."
ADMIN_ANNOUNCE_POSTED = "اعلامیه توی کانال پست شد."
