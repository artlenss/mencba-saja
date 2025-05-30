import telebot
from telebot.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, Message,
    CallbackQuery
)
import sqlite3
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
import logging
import sys
from functools import wraps
from typing import Optional, List, Tuple, Any, Dict

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('bot.log', encoding='utf-8') # Ensure UTF-8 for logs
    ]
)
logger = logging.getLogger(__name__)

# --- Konstanta ---
DB_NAME = 'store_enhanced.db'

class AdminCallbackData:
    # Produk
    ADD_ACCOUNT = "adm_add_account"
    LIST_ACCOUNTS = "adm_list_accounts"
    CHECK_STOCK_DETAIL = "adm_check_stock_detail"
    DELETE_ACCOUNT_PROMPT = "adm_delete_account_prompt"
    CONFIRM_DELETE_ACCOUNT_PREFIX = "adm_confirm_delete_acc_"
    CANCEL_BACK_PRODUCT = "adm_cancel_back_product"
    BACK_TO_PRODUCT = "adm_back_product"

    # Keuangan
    PAYMENT_METHODS = "adm_payment_methods"
    PRICE_SETTINGS = "adm_price_settings"
    SALES_REPORT = "adm_sales_report"
    PENDING_PAYMENTS_MENU = "adm_pending_payments_menu"
    ADD_PAYMENT_METHOD = "adm_add_payment_method"
    TOGGLE_PAYMENT_METHOD_PREFIX = "adm_toggle_pm_"
    DELETE_PAYMENT_METHOD_PREFIX = "adm_delete_pm_"
    CONFIRM_DELETE_PAYMENT_METHOD_PREFIX = "adm_confirm_delete_pm_"
    CANCEL_BACK_FINANCE = "adm_cancel_back_finance"
    BACK_TO_FINANCE = "adm_back_finance"

    # Pengaturan
    TOGGLE_MAINTENANCE = "adm_toggle_maintenance"
    # PRICE_SETTINGS dan PAYMENT_METHODS bisa diakses dari menu Keuangan & Pengaturan

    # Umum
    CANCEL_ACTION = "adm_cancel_action" # General cancel, might remove current message's keyboard
# --- End Konstanta ---

try:
    logger.info("Memuat environment variables...")
    load_dotenv()

    TOKEN: Optional[str] = os.getenv('BOT_TOKEN')
    ADMIN_ID_STR: Optional[str] = os.getenv('ADMIN_ID')
    BOT_USERNAME: Optional[str] = os.getenv('BOT_USERNAME')
    OWNER_USERNAME: Optional[str] = os.getenv('OWNER_USERNAME')
    STORE_NAME: Optional[str] = os.getenv('STORE_NAME', 'Toko Online Bot') # Default jika tidak diset
    ADMIN_USERNAME: Optional[str] = os.getenv('ADMIN_USERNAME')
    PAYMENT_METHODS_STR: str = os.getenv('PAYMENT_METHODS', 'DANA,OVO,GOPAY,BCA,BRI')
    PAYMENT_METHODS: List[str] = PAYMENT_METHODS_STR.split(',') if PAYMENT_METHODS_STR else []

    if not all([TOKEN, ADMIN_ID_STR, BOT_USERNAME, OWNER_USERNAME, STORE_NAME, ADMIN_USERNAME]):
        raise ValueError("Variabel lingkungan yang wajib ada hilang (TOKEN, ADMIN_ID, BOT_USERNAME, OWNER_USERNAME, STORE_NAME, ADMIN_USERNAME)")

    ADMIN_ID: int
    try:
        ADMIN_ID = int(ADMIN_ID_STR)
    except ValueError:
        raise ValueError("Variabel lingkungan ADMIN_ID harus berupa integer (Telegram User ID).")

    print(f"=== {STORE_NAME} Bot (Enhanced) ===")
    print("Memulai bot...")

    logger.info("Inisialisasi bot...")
    bot = telebot.TeleBot(TOKEN, parse_mode='Markdown') # Set parse_mode global ke Markdown
    me = bot.get_me()
    print(f"Nama Bot: {me.first_name}")
    print(f"Username Bot: @{me.username}")


    def init_db() -> None:
        """Inisialisasi atau update skema database."""
        print("Membuat/memperbarui database...")
        try:
            with sqlite3.connect(DB_NAME) as conn:
                c = conn.cursor()
                c.execute('PRAGMA foreign_keys = ON;')

                c.execute('''CREATE TABLE IF NOT EXISTS accounts
                             (id INTEGER PRIMARY KEY AUTOINCREMENT,
                              email TEXT UNIQUE NOT NULL,
                              password TEXT NOT NULL,
                              notes TEXT,
                              sold INTEGER DEFAULT 0,
                              date_added TEXT NOT NULL,
                              sold_to_username TEXT,
                              sold_to_id INTEGER,
                              sold_date TEXT)''')

                c.execute('''CREATE TABLE IF NOT EXISTS customers
                             (telegram_id INTEGER PRIMARY KEY,
                              username TEXT,
                              join_date TEXT,
                              is_blocked INTEGER DEFAULT 0)''')

                c.execute('''CREATE TABLE IF NOT EXISTS sales
                             (id INTEGER PRIMARY KEY AUTOINCREMENT,
                              account_id INTEGER,
                              buyer_id INTEGER NOT NULL,
                              buyer_username TEXT,
                              amount TEXT NOT NULL,
                              payment_method TEXT,
                              payment_proof TEXT,
                              status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'completed', 'cancelled', 'failed')),
                              created_date TEXT NOT NULL,
                              completed_date TEXT,
                              admin_notes TEXT, -- Ditambahkan
                              FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE SET NULL,
                              FOREIGN KEY(buyer_id) REFERENCES customers(telegram_id))''')

                c.execute('''CREATE TABLE IF NOT EXISTS payment_methods
                             (id INTEGER PRIMARY KEY AUTOINCREMENT,
                              method TEXT UNIQUE NOT NULL,
                              number TEXT NOT NULL,
                              holder_name TEXT NOT NULL,
                              active INTEGER DEFAULT 1)''')

                c.execute('''CREATE TABLE IF NOT EXISTS settings
                             (key TEXT PRIMARY KEY,
                              value TEXT)''')

                default_settings: Dict[str, str] = {
                    'price': '50000',
                    'maintenance_mode': 'off',
                    'min_purchase': '1',
                    'max_purchase': '1'
                }
                for key, value in default_settings.items():
                    c.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', (key, value))

                # Migrasi skema (jika diperlukan)
                try:
                    c.execute('ALTER TABLE sales ADD COLUMN payment_method TEXT;')
                    logger.info("Kolom 'payment_method' ditambahkan ke tabel 'sales'.")
                except sqlite3.OperationalError:
                    pass
                try:
                    c.execute('ALTER TABLE sales ADD COLUMN admin_notes TEXT;')
                    logger.info("Kolom 'admin_notes' ditambahkan ke tabel 'sales'.")
                except sqlite3.OperationalError:
                    pass

                conn.commit()
            print("Database berhasil diinisialisasi!")
        except sqlite3.Error as e:
            logger.critical(f"Gagal inisialisasi database: {e}", exc_info=True)
            print(f"KRITIKAL: Gagal inisialisasi database - {e}")
            sys.exit(1)

    def get_setting(key: str) -> Optional[str]:
        """Mengambil nilai pengaturan dari database."""
        try:
            with sqlite3.connect(DB_NAME) as conn:
                c = conn.cursor()
                c.execute('SELECT value FROM settings WHERE key = ?', (key,))
                result = c.fetchone()
            return result[0] if result else None
        except sqlite3.Error as e:
            logger.error(f"Error mengambil pengaturan {key}: {e}")
            return None

    def set_setting(key: str, value: str) -> bool:
        """Menyimpan nilai pengaturan ke database."""
        try:
            with sqlite3.connect(DB_NAME) as conn:
                c = conn.cursor()
                c.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, value))
                conn.commit()
            return True
        except sqlite3.Error as e:
            logger.error(f"Error menyimpan pengaturan {key} ke {value}: {e}")
            return False

    def format_rupiah(amount_str: Any) -> str:
        """Memformat angka menjadi format Rupiah."""
        try:
            cleaned_amount = ''.join(filter(str.isdigit, str(amount_str)))
            if not cleaned_amount: return str(amount_str) # Jika kosong setelah dibersihkan
            amount = float(cleaned_amount)
            return f"Rp {amount:,.0f}".replace(',', '.')
        except (ValueError, TypeError):
            return str(amount_str)

    def is_admin(user_id: int) -> bool:
        """Memeriksa apakah user_id adalah admin."""
        return user_id == ADMIN_ID

    def check_maintenance(func):
        """Decorator untuk memeriksa mode maintenance."""
        @wraps(func)
        def decorated_function(message_or_call: Any, *args, **kwargs):
            user_id = message_or_call.from_user.id
            message_obj = message_or_call if hasattr(message_or_call, 'chat') else message_or_call.message

            if get_setting('maintenance_mode') == 'on' and not is_admin(user_id):
                bot.reply_to(
                    message_obj,
                    "🛠 *BOT SEDANG MAINTENANCE*\n\nMohon tunggu beberapa saat. Terima kasih!",
                )
                if hasattr(message_or_call, 'id') and not hasattr(message_or_call, 'chat'): # CallbackQuery
                    bot.answer_callback_query(message_or_call.id, "Bot sedang maintenance.")
                return
            return func(message_or_call, *args, **kwargs)
        return decorated_function

    def get_admin_keyboard() -> ReplyKeyboardMarkup:
        """Membuat keyboard admin."""
        markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        markup.add(
            KeyboardButton("📦 Produk"), KeyboardButton("💰 Keuangan"),
            KeyboardButton("⚙️ Pengaturan"), KeyboardButton("📊 Statistik"),
            KeyboardButton("📢 Broadcast"), KeyboardButton("⏳ Pemb. Pending"),
            KeyboardButton("🔄 Refresh")
        )
        return markup

    def get_user_keyboard() -> ReplyKeyboardMarkup:
        """Membuat keyboard user."""
        markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        markup.add(
            KeyboardButton("🛒 Beli Akun"), KeyboardButton("📦 Cek Stok"),
            KeyboardButton("💰 Cek Harga"), KeyboardButton("❓ Bantuan")
        )
        return markup

    @bot.message_handler(commands=['start'])
    @check_maintenance
    def start_command(message: Message) -> None:
        """Handler untuk perintah /start."""
        user_id = message.from_user.id
        username = message.from_user.username if message.from_user.username else f"user_{user_id}"
        
        try:
            with sqlite3.connect(DB_NAME) as conn:
                c = conn.cursor()
                c.execute('''INSERT OR IGNORE INTO customers 
                             (telegram_id, username, join_date)
                             VALUES (?, ?, ?)''',
                          (user_id, username, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Error mendaftarkan customer {user_id}: {e}")

        markup: ReplyKeyboardMarkup
        msg_text: str
        if is_admin(user_id):
            markup = get_admin_keyboard()
            msg_text = (
                f"👑 *Selamat Datang, Admin Panel {STORE_NAME}!* (Enhanced)\n\n"
                "Gunakan tombol di bawah untuk mengelola bot.\n"
                "⏳ *Pemb. Pending*: Cek transaksi yang butuh approval.\n"
                "📦 *Produk*: Kelola stok (tambah, lihat, hapus).\n"
                "💰 *Keuangan*: Atur harga, metode bayar, laporan penjualan.\n"
                "⚙️ *Pengaturan*: Atur mode maintenance, harga, dll.\n"
                "📊 *Statistik*: Lihat statistik penjualan dan pengguna.\n"
                "📢 *Broadcast*: Kirim pesan ke semua pengguna aktif.\n"
                "🔄 *Refresh*: Muat ulang keyboard admin."
            )
        else:
            markup = get_user_keyboard()
            msg_text = (
                f"🎉 *Selamat datang di {STORE_NAME}!* (Enhanced) 🎉\n\n"
                f"Kami menyediakan akun Blackbox.ai premium.\n"
                "Silakan gunakan menu di bawah ini:\n"
                "🛒 *Beli Akun*: Memulai proses pembelian otomatis.\n"
                "📦 *Cek Stok*: Melihat ketersediaan akun saat ini.\n"
                "💰 *Cek Harga*: Informasi harga per akun.\n"
                "❓ *Bantuan*: Informasi kontak dan bantuan."
            )
        bot.reply_to(message, msg_text, reply_markup=markup)

    # --- USER COMMANDS (ENHANCED PURCHASE FLOW) ---
    @bot.message_handler(func=lambda message: message.text == "🛒 Beli Akun" and not is_admin(message.from_user.id))
    @check_maintenance
    def buy_account_user(message: Message) -> None:
        """Handler untuk user yang ingin membeli akun."""
        try:
            with sqlite3.connect(DB_NAME) as conn:
                c = conn.cursor()
                c.execute('SELECT COUNT(*) FROM accounts WHERE sold = 0')
                stock = c.fetchone()[0]

                if stock == 0:
                    bot.reply_to(message, "Mohon maaf, stok akun saat ini sedang habis. 😔 Silakan cek kembali nanti.")
                    return

                price_str = get_setting('price')
                if not price_str: # Seharusnya tidak terjadi jika default ada
                    bot.reply_to(message, f"⚠️ Harga belum diatur oleh admin. Hubungi @{ADMIN_USERNAME}.")
                    return
                price_formatted = format_rupiah(price_str)

                c.execute('SELECT method, number, holder_name FROM payment_methods WHERE active = 1')
                active_payments: List[Tuple[str, str, str]] = c.fetchall()
            
            payment_info = "💳 *Metode Pembayaran Tersedia*:\n"
            if active_payments:
                for method, number, holder_name in active_payments:
                    payment_info += f"  • *{method}*: `{number}` (a/n *{holder_name}*)\n"
            else:
                payment_info += "  ⚠️ Saat ini admin belum mengatur metode pembayaran. Silakan hubungi admin.\n"
                bot.reply_to(message, f"{payment_info}\nUntuk info lebih lanjut hubungi @{ADMIN_USERNAME}.")
                return

            markup = InlineKeyboardMarkup(row_width=1)
            markup.add(InlineKeyboardButton("✅ Saya Sudah Bayar & Kirim Bukti", callback_data="user_confirm_purchase_send_proof"))
            markup.add(InlineKeyboardButton(f"❓ Tanya Admin (@{ADMIN_USERNAME})", url=f"https://t.me/{ADMIN_USERNAME}"))

            buy_message = (
                f"✨ *Pembelian Akun Premium {STORE_NAME}*\n\n"
                f"Harga per akun: *{price_formatted}*\n"
                f"Stok tersedia: *{stock} akun*\n\n"
                f"{payment_info}\n"
                f"➡️ *Langkah Pembelian*:\n"
                f"1. Lakukan pembayaran sejumlah harga di atas ke salah satu metode yang tersedia.\n"
                f"2. Klik tombol '*✅ Saya Sudah Bayar & Kirim Bukti*' di bawah ini.\n"
                f"3. Kirimkan *BUKTI TRANSFER* Anda (berupa foto/screenshot).\n"
                f"4. Admin akan memverifikasi dan akun akan dikirim otomatis jika disetujui.\n\n"
                f"Terima kasih! 😊"
            )
            bot.reply_to(message, buy_message, reply_markup=markup)

        except sqlite3.Error as e:
            logger.error(f"DB Error di buy_account_user: {e}")
            bot.reply_to(message, "❌ Terjadi kesalahan database. Mohon coba lagi nanti.")
        except Exception as e:
            logger.error(f"General Error di buy_account_user: {e}", exc_info=True)
            bot.reply_to(message, "❌ Ups! Ada kendala. Silakan hubungi admin.")

    @bot.callback_query_handler(func=lambda call: call.data == "user_confirm_purchase_send_proof")
    @check_maintenance
    def cb_user_confirms_purchase(call: CallbackQuery) -> None:
        """Callback setelah user mengklik 'Saya Sudah Bayar & Kirim Bukti'."""
        bot.answer_callback_query(call.id)
        
        try:
            with sqlite3.connect(DB_NAME) as conn:
                c = conn.cursor()
                c.execute('SELECT COUNT(*) FROM accounts WHERE sold = 0')
                stock = c.fetchone()[0]
            if stock == 0:
                bot.send_message(call.message.chat.id, "⚠️ Maaf, stok habis tepat sebelum Anda konfirmasi. Silakan cek lagi nanti.")
                bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
                return
        except sqlite3.Error as e:
            logger.error(f"DB error memeriksa stok di cb_user_confirms_purchase: {e}")
            bot.send_message(call.message.chat.id, "❌ Gagal memeriksa stok. Coba lagi dari menu.")
            return

        msg_ask_proof = bot.send_message(
            call.message.chat.id,
            "Baik! 👍 Silakan kirim *satu pesan* berisi *foto atau screenshot bukti pembayaran* Anda.\n\nPastikan bukti transfer jelas dan terbaca ya.",
        )
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except telebot.apihelper.ApiTelegramException as e_edit:
            logger.warning(f"Gagal menghapus markup tombol lama: {e_edit}")

        bot.register_next_step_handler(msg_ask_proof, process_payment_proof_submission)

    def process_payment_proof_submission(message: Message) -> None:
        """Memproses bukti pembayaran yang dikirim user."""
        user_id = message.from_user.id
        username = message.from_user.username if message.from_user.username else f"user_{user_id}"
        file_id: Optional[str] = None
        
        if message.content_type == 'photo':
            file_id = message.photo[-1].file_id
        elif message.content_type == 'document' and message.document.mime_type and message.document.mime_type.startswith('image/'):
            file_id = message.document.file_id
        else:
            bot.reply_to(message, "⚠️ Format file tidak didukung atau bukan gambar. Harap kirim bukti pembayaran berupa *gambar/foto* atau *screenshot*.\nUlangi dari menu '🛒 Beli Akun'.")
            return

        if not file_id:
            bot.reply_to(message, "⚠️ Gagal mendapatkan file bukti pembayaran. Silakan coba lagi.\nUlangi dari menu '🛒 Beli Akun'.")
            return

        price_str = get_setting('price')
        if not price_str:
            bot.reply_to(message, "Kesalahan: Harga produk tidak terset. Hubungi admin.")
            logger.error("Harga produk tidak ditemukan saat proses submit bukti.")
            return
            
        current_time_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        try:
            with sqlite3.connect(DB_NAME) as conn:
                c = conn.cursor()
                
                c.execute('SELECT COUNT(*) FROM accounts WHERE sold = 0') # Cek stok terakhir
                stock_final_check = c.fetchone()[0]
                if stock_final_check == 0:
                    bot.reply_to(message, "❌ Maaf, stok akun baru saja habis saat Anda mengirim bukti. Pembelian tidak dapat diproses. Silakan hubungi admin jika sudah transfer.")
                    return

                c.execute('''INSERT INTO sales 
                             (buyer_id, buyer_username, amount, payment_proof, status, created_date, account_id) 
                             VALUES (?, ?, ?, ?, 'pending', ?, NULL)''',
                          (user_id, username, price_str, file_id, current_time_str))
                sale_id = c.lastrowid
                conn.commit()

            bot.reply_to(
                message,
                f"✅ Bukti pembayaran Anda (Sale ID: `{sale_id}`) telah diterima!\n"
                f"Admin akan segera memverifikasi pembayaran Anda. Anda akan dihubungi setelah diverifikasi.\n"
                f"Harap tunggu dengan sabar. Terima kasih! 😊",
            )

            admin_message = (
                f"🔔 *PEMBAYARAN BARU MENUNGGU VERIFIKASI!*\n\n"
                f"Sale ID: `{sale_id}`\n"
                f"Dari: @{username if username != f'user_{user_id}' else f'User ID {user_id}'}\n"
                f"Waktu: {current_time_str}\n"
                f"Jumlah: {format_rupiah(price_str)}\n\n"
                f"Bukti pembayaran ada di pesan yang diteruskan.\n"
                f"👉 Setujui: `/approve {sale_id}`\n"
                f"👉 Tolak: `/reject {sale_id} [ALASAN]`"
            )
            try:
                bot.forward_message(chat_id=ADMIN_ID, from_chat_id=message.chat.id, message_id=message.message_id)
                bot.send_message(ADMIN_ID, admin_message)
            except Exception as e_admin_notify:
                logger.error(f"Gagal forward bukti atau notif admin untuk Sale ID {sale_id}: {e_admin_notify}")
                bot.send_message(ADMIN_ID, f"🔔 Pembayaran baru (Sale ID: {sale_id}) dari @{username} (User ID: {user_id}) menunggu verifikasi. File ID Bukti: {file_id}. Gunakan `/approve {sale_id}` atau `/reject {sale_id} [ALASAN]`.")

        except sqlite3.Error as e:
            logger.error(f"DB Error memproses bukti bayar untuk user {user_id}: {e}", exc_info=True)
            bot.reply_to(message, "❌ Terjadi kesalahan database saat menyimpan data pembelian Anda. Mohon hubungi admin.")
        except Exception as e:
            logger.error(f"General Error memproses bukti bayar untuk user {user_id}: {e}", exc_info=True)
            bot.reply_to(message, "❌ Terjadi kesalahan tak terduga. Mohon hubungi admin.")

    @bot.message_handler(func=lambda message: message.text == "📦 Cek Stok" and not is_admin(message.from_user.id))
    @check_maintenance
    def check_stock_user(message: Message) -> None:
        try:
            with sqlite3.connect(DB_NAME) as conn:
                c = conn.cursor()
                c.execute('SELECT COUNT(*) FROM accounts WHERE sold = 0')
                stock = c.fetchone()[0]
            
            if stock > 0:
                bot.reply_to(message, f"📦 Stok akun {STORE_NAME} saat ini: *{stock} akun*.\nSegera lakukan pembelian sebelum kehabisan! 😉")
            else:
                bot.reply_to(message, f"😔 Mohon maaf, stok akun {STORE_NAME} saat ini sedang *kosong*. Silakan cek kembali nanti ya!")
        except sqlite3.Error as e:
            logger.error(f"DB Error di check_stock_user: {e}")
            bot.reply_to(message, "❌ Gagal mengambil info stok. Coba lagi nanti.")

    @bot.message_handler(func=lambda message: message.text == "💰 Cek Harga" and not is_admin(message.from_user.id))
    @check_maintenance
    def check_price_user(message: Message) -> None:
        price_str = get_setting('price')
        if price_str:
            price_formatted = format_rupiah(price_str)
            bot.reply_to(message, f"💰 Harga satu akun premium {STORE_NAME} adalah: *{price_formatted}*.")
        else:
            bot.reply_to(message, f"⚠️ Informasi harga belum diatur. Silakan hubungi admin @{ADMIN_USERNAME}.")

    @bot.message_handler(func=lambda message: message.text == "❓ Bantuan" and not is_admin(message.from_user.id))
    @check_maintenance
    def help_user(message: Message) -> None:
        help_text = (
            f"❓ *Pusat Bantuan {STORE_NAME}*\n\n"
            "Berikut adalah perintah cepat:\n"
            "  🛒 *Beli Akun* - Mulai proses pembelian.\n"
            "  📦 *Cek Stok* - Lihat ketersediaan akun.\n"
            "  💰 *Cek Harga* - Info harga per akun.\n\n"
            f"Jika ada kendala atau pertanyaan, hubungi Admin @{ADMIN_USERNAME}.\n"
            f"Owner: @{OWNER_USERNAME}."
        )
        markup = InlineKeyboardMarkup(row_width=1)
        markup.add(InlineKeyboardButton(f"💬 Hubungi Admin (@{ADMIN_USERNAME})", url=f"https://t.me/{ADMIN_USERNAME}"))
        if OWNER_USERNAME and OWNER_USERNAME != ADMIN_USERNAME :
             markup.add(InlineKeyboardButton(f"👑 Hubungi Owner (@{OWNER_USERNAME})", url=f"https://t.me/{OWNER_USERNAME}"))
        bot.reply_to(message, help_text, reply_markup=markup)

    # --- ADMIN COMMANDS AND CALLBACKS ---
    @bot.message_handler(func=lambda message: message.text == "📦 Produk" and is_admin(message.from_user.id))
    def product_menu_admin(message: Message) -> None:
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("➕ Tambah Akun", callback_data=AdminCallbackData.ADD_ACCOUNT),
            InlineKeyboardButton("📋 List Semua Akun", callback_data=AdminCallbackData.LIST_ACCOUNTS),
            InlineKeyboardButton("📦 Stok Tersedia (Detail)", callback_data=AdminCallbackData.CHECK_STOCK_DETAIL),
            InlineKeyboardButton("🗑 Hapus Akun", callback_data=AdminCallbackData.DELETE_ACCOUNT_PROMPT)
        )
        bot.reply_to(message, "📦 *Menu Manajemen Produk*\n\nPilih tindakan:", reply_markup=markup)

    @bot.message_handler(func=lambda message: message.text == "💰 Keuangan" and is_admin(message.from_user.id))
    def finance_menu_admin(message: Message) -> None:
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("💳 Metode Pembayaran", callback_data=AdminCallbackData.PAYMENT_METHODS),
            InlineKeyboardButton("💲 Atur Harga Akun", callback_data=AdminCallbackData.PRICE_SETTINGS),
            InlineKeyboardButton("📊 Laporan Penjualan", callback_data=AdminCallbackData.SALES_REPORT),
            InlineKeyboardButton("⏳ Pembayaran Pending", callback_data=AdminCallbackData.PENDING_PAYMENTS_MENU)
        )
        bot.reply_to(message, "💰 *Menu Manajemen Keuangan*\n\nPilih tindakan:", reply_markup=markup)
    
    # Fungsi terpisah untuk menampilkan pembayaran pending (dipanggil dari ReplyKeyboard dan InlineKeyboard)
    def display_pending_payments_admin(chat_id: int, message_id_to_edit: Optional[int] = None, from_reply_keyboard: bool = False) -> None:
        """Menampilkan daftar pembayaran pending untuk admin."""
        try:
            with sqlite3.connect(DB_NAME) as conn:
                c = conn.cursor()
                c.execute("""
                    SELECT s.id, s.buyer_username, s.buyer_id, s.amount, s.created_date, s.payment_method, s.payment_proof
                    FROM sales s
                    WHERE s.status = 'pending'
                    ORDER BY s.created_date ASC 
                """)
                pending_tx: List[Tuple[int, str, int, str, str, Optional[str], Optional[str]]] = c.fetchall()

            response_text = "⏳ *Daftar Pembayaran Pending*\n(Urut berdasarkan terlama)\n\n"
            if not pending_tx:
                response_text += "✅ Tidak ada pembayaran menunggu persetujuan."
            else:
                for tx_id, username, buyer_id, amount, date_created, _, proof_file_id in pending_tx:
                    buyer_name_display = username if username and username != f"user_{buyer_id}" else f"User ID {buyer_id}"
                    buyer_contact = f"@{username}" if username and username != f"user_{buyer_id}" else f"ID: {buyer_id}"
                    response_text += (
                        f"🆔 Sale ID: `{tx_id}`\n"
                        f"👤 Pembeli: {buyer_contact}\n"
                        f"💰 Jumlah: {format_rupiah(amount)}\n"
                        f"🧾 Bukti File ID: `{proof_file_id if proof_file_id else 'TIDAK ADA'}`\n"
                        f"🗓 Dibuat: {datetime.strptime(date_created, '%Y-%m-%d %H:%M:%S').strftime('%d %b %y, %H:%M')}\n"
                        f"👉 Setujui: `/approve {tx_id}`\n"
                        f"👉 Tolak: `/reject {tx_id} [ALASAN]`\n"
                        f"--------------------\n"
                    )
            
            if len(response_text) > 4096: # Telegram message length limit
                response_text = response_text[:4000] + "\n\n⚠️ Daftar terlalu panjang, beberapa item mungkin terpotong..."

            reply_markup_pending = InlineKeyboardMarkup()
            if not from_reply_keyboard or message_id_to_edit : # Hanya tambahkan tombol kembali jika dari inline atau ada message_id_to_edit
                reply_markup_pending.add(InlineKeyboardButton("🔙 Kembali ke Menu Keuangan", callback_data=AdminCallbackData.BACK_TO_FINANCE))

            if message_id_to_edit and not from_reply_keyboard:
                try:
                    bot.edit_message_text(response_text, chat_id, message_id_to_edit, reply_markup=reply_markup_pending)
                except telebot.apihelper.ApiTelegramException as e_edit:
                    if "message is not modified" not in str(e_edit).lower():
                        logger.warning(f"Gagal edit pesan pending payments: {e_edit}, mengirim pesan baru.")
                        bot.send_message(chat_id, response_text, reply_markup=reply_markup_pending if not from_reply_keyboard else None)
            else: # Jika dari reply keyboard atau edit gagal dan perlu kirim baru
                bot.send_message(chat_id, response_text, reply_markup=reply_markup_pending if not from_reply_keyboard else None)
        
        except sqlite3.Error as e:
            logger.error(f"DB Error di display_pending_payments_admin: {e}", exc_info=True)
            bot.send_message(chat_id, "❌ Gagal mengambil daftar pembayaran pending karena error database.")
        except Exception as e:
            logger.error(f"Error saat generate daftar pembayaran pending: {e}", exc_info=True)
            bot.send_message(chat_id, "❌ Terjadi error internal saat menampilkan daftar pending. Cek log.")

    @bot.message_handler(func=lambda message: message.text == "⏳ Pemb. Pending" and is_admin(message.from_user.id))
    def pending_payments_menu_shortcut(message: Message) -> None:
        """Handler untuk tombol 'Pemb. Pending' dari ReplyKeyboard."""
        display_pending_payments_admin(message.chat.id, from_reply_keyboard=True)

    @bot.message_handler(func=lambda message: message.text == "⚙️ Pengaturan" and is_admin(message.from_user.id))
    def settings_menu_admin(message: Message) -> None:
        markup = InlineKeyboardMarkup(row_width=1)
        maintenance_status_val = get_setting('maintenance_mode')
        maintenance_status = "ON 🟢" if maintenance_status_val == 'on' else "OFF 🔴"
        markup.add(
            InlineKeyboardButton(f"🛠 Mode Maintenance: {maintenance_status}", callback_data=AdminCallbackData.TOGGLE_MAINTENANCE),
            InlineKeyboardButton("💲 Atur Harga Akun", callback_data=AdminCallbackData.PRICE_SETTINGS),
            InlineKeyboardButton("💳 Metode Pembayaran", callback_data=AdminCallbackData.PAYMENT_METHODS)
        )
        current_price = format_rupiah(get_setting('price'))
        settings_text = (
            f"⚙️ *Pengaturan Bot - {STORE_NAME}*\n\n"
            f"Harga Saat Ini: `{current_price}`\n"
            f"Mode Maintenance: `{maintenance_status}`\n\n"
            "Pilih pengaturan:"
        )
        bot.reply_to(message, settings_text, reply_markup=markup)

    @bot.message_handler(func=lambda message: message.text == "📊 Statistik" and is_admin(message.from_user.id))
    def stats_menu_admin(message: Message) -> None:
        try:
            with sqlite3.connect(DB_NAME) as conn:
                c = conn.cursor()
                c.execute('SELECT COUNT(*) FROM accounts')
                total_accounts = c.fetchone()[0]
                c.execute('SELECT COUNT(*) FROM accounts WHERE sold = 0')
                available_accounts = c.fetchone()[0]
                sold_accounts = total_accounts - available_accounts
                
                c.execute("SELECT COUNT(*), SUM(CAST(REPLACE(REPLACE(amount, '.', ''), ',', '') AS REAL)) FROM sales WHERE status = 'completed'")
                completed_sales_data = c.fetchone()
                total_completed_sales = completed_sales_data[0] or 0
                total_revenue = completed_sales_data[1] or 0.0

                today_str = datetime.now().strftime('%Y-%m-%d')
                c.execute("""
                    SELECT COUNT(*), SUM(CAST(REPLACE(REPLACE(amount, '.', ''), ',', '') AS REAL))
                    FROM sales 
                    WHERE status = 'completed' AND DATE(completed_date) = ? 
                """, (today_str,)) # Menggunakan completed_date untuk pendapatan harian
                today_sales_data = c.fetchone()
                today_sales_count = today_sales_data[0] or 0
                today_revenue = today_sales_data[1] or 0.0

                c.execute("SELECT COUNT(*) FROM customers WHERE is_blocked = 0")
                total_users = c.fetchone()[0]
            stats_text = (
                f"📊 *Statistik Bot - {STORE_NAME}*\n\n"
                f"👤 Pengguna Aktif: {total_users}\n\n"
                f"📦 Akun:\n"
                f"  • Total di DB: {total_accounts}\n"
                f"  • Tersedia: {available_accounts}\n"
                f"  • Terjual: {sold_accounts}\n\n"
                f"📈 Penjualan:\n"
                f"  • Transaksi Sukses: {total_completed_sales}\n"
                f"  • Total Pendapatan: {format_rupiah(total_revenue)}\n\n"
                f"📅 Hari Ini ({datetime.now().strftime('%d %b %Y')}):\n"
                f"  • Transaksi Sukses: {today_sales_count}\n"
                f"  • Pendapatan Hari Ini: {format_rupiah(today_revenue)}"
            )
            bot.reply_to(message, stats_text)
        except sqlite3.Error as e:
            logger.error(f"Error di stats_menu_admin: {e}", exc_info=True)
            bot.reply_to(message, "❌ Error database saat mengambil statistik.")
        except Exception as e:
            logger.error(f"Error tak terduga di stats_menu_admin: {e}", exc_info=True)
            bot.reply_to(message, "❌ Error tak terduga. Hubungi developer.")

    @bot.message_handler(func=lambda message: message.text == "📢 Broadcast" and is_admin(message.from_user.id))
    def broadcast_command_admin(message: Message) -> None:
        msg = bot.reply_to(
            message,
            "📝 *Kirim Pesan Broadcast*\nMasukkan pesan (Markdown didukung). Pesan akan memiliki prefix pemberitahuan otomatis.\nKetik /cancel_broadcast untuk batal.",
        )
        bot.register_next_step_handler(msg, process_broadcast_message)

    def process_broadcast_message(message: Message) -> None:
        if not is_admin(message.from_user.id): return # Extra check
        if message.text == '/cancel_broadcast':
            bot.reply_to(message, "Broadcast dibatalkan.")
            return

        broadcast_text = message.text
        sent_count = 0
        failed_count = 0
        users_to_block: List[int] = []

        try:
            with sqlite3.connect(DB_NAME) as conn_select:
                c_select = conn_select.cursor()
                c_select.execute('SELECT telegram_id FROM customers WHERE is_blocked = 0')
                users: List[Tuple[int]] = c_select.fetchall()

            if not users:
                bot.reply_to(message, "ℹ️ Tidak ada pengguna aktif untuk broadcast.")
                return

            bot.reply_to(message, f"⏳ Mengirim broadcast ke {len(users)} pengguna...")
            
            for (user_id,) in users:
                try:
                    bot.send_message(user_id, f"🔔 *Pesan dari Admin {STORE_NAME}* 🔔\n\n{broadcast_text}")
                    sent_count += 1
                except telebot.apihelper.ApiTelegramException as e_api:
                    logger.warning(f"Gagal mengirim broadcast ke {user_id}: {e_api}")
                    failed_count += 1
                    err_msg = str(e_api).lower()
                    if any(s in err_msg for s in ["bot was blocked by the user", "user is deactivated", "chat not found", "bot_blocked", "user_deleted", "forbidden: bot was kicket from the group chat"]): # Tambah variasi error
                        users_to_block.append(user_id)
                except Exception as e_general:
                    logger.error(f"Error tak terduga saat mengirim broadcast ke {user_id}: {e_general}")
                    failed_count +=1
            
            if users_to_block:
                try:
                    with sqlite3.connect(DB_NAME) as conn_update:
                        c_update = conn_update.cursor()
                        for user_id_block in users_to_block:
                            c_update.execute("UPDATE customers SET is_blocked = 1 WHERE telegram_id = ?", (user_id_block,))
                        conn_update.commit()
                        logger.info(f"{len(users_to_block)} pengguna ditandai sebagai diblokir setelah broadcast.")
                except sqlite3.Error as e_db_block:
                     logger.error(f"Error DB saat update pengguna diblokir: {e_db_block}")
            
            bot.reply_to(
                message,
                f"✅ *Broadcast Selesai!*\n"
                f"👍 Terkirim: {sent_count} pengguna.\n"
                f"👎 Gagal: {failed_count} pengguna (termasuk yang memblokir bot)."
            )
        except sqlite3.Error as e:
            logger.error(f"Database error di process_broadcast_message: {e}", exc_info=True)
            bot.reply_to(message, "❌ Error database saat broadcast.")
        except Exception as e:
            logger.error(f"General error di process_broadcast_message: {e}", exc_info=True)
            bot.reply_to(message, "❌ Error umum saat broadcast.")

    @bot.message_handler(func=lambda message: message.text == "🔄 Refresh" and is_admin(message.from_user.id))
    def refresh_admin_keyboard(message: Message) -> None:
        bot.reply_to(message, "🔄 Keyboard admin dimuat ulang.", reply_markup=get_admin_keyboard())
        # Untuk menampilkan pesan selamat datang lagi, bisa panggil start_command(message)
        # Namun, itu akan mendaftarkan user lagi (walaupun ada IGNORE), jadi reply_to cukup.

    # --- Admin Callback Handler Utama ---
    @bot.callback_query_handler(func=lambda call: call.data.startswith('adm_'))
    def handle_admin_callback(call: CallbackQuery) -> None:
        user_id = call.from_user.id
        if not is_admin(user_id):
            bot.answer_callback_query(call.id, "⚠️ Akses ditolak!")
            return
        
        bot.answer_callback_query(call.id) # Acknowledge callback secepatnya
        chat_id = call.message.chat.id
        message_id = call.message.message_id
        data = call.data

        try:
            # --- Product Management Callbacks ---
            if data == AdminCallbackData.ADD_ACCOUNT:
                msg_prompt = bot.send_message(
                    chat_id,
                    "➕ *Tambah Akun Baru*\nFormat: `email|password|catatan (opsional)`\nContoh: `user@ex.com|Pass123|Akun Premium`\n\nKetik /cancel untuk batal atau gunakan tombol di bawah.",
                    reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("❌ Batal & Kembali ke Produk", callback_data=AdminCallbackData.CANCEL_BACK_PRODUCT))
                )
                bot.register_next_step_handler(msg_prompt, process_add_account_admin)

            elif data == AdminCallbackData.LIST_ACCOUNTS:
                try:
                    with sqlite3.connect(DB_NAME) as conn:
                        c = conn.cursor()
                        c.execute('SELECT id, email, password, notes, sold, sold_to_username, sold_date, date_added FROM accounts ORDER BY id DESC')
                        all_accounts: List[Tuple[int, str, str, Optional[str], int, Optional[str], Optional[str], str]] = c.fetchall()
                    
                    response_text = "📋 *Daftar Semua Akun*\n(Terbaru di atas)\n\n"
                    if not all_accounts:
                        response_text += "Tidak ada akun di database."
                    else:
                        for acc_id, email, acc_pass, notes, sold, sold_to, sold_dt, date_added in all_accounts:
                            status = "✅ Terjual" if sold else "☑️ Tersedia"
                            pass_display = f"{acc_pass[:3]}****{acc_pass[-1:]}" if acc_pass and len(acc_pass) > 4 else "****"
                            sold_info = f" kpd @{sold_to} ({datetime.strptime(sold_dt, '%Y-%m-%d %H:%M:%S').strftime('%d %b %y') if sold_dt else 'N/A'})" if sold else ""
                            notes_info = f"\n   📝 Catatan: {notes}" if notes else ""
                            added_info = f"\n   ➕ Ditambah: {datetime.strptime(date_added, '%Y-%m-%d %H:%M:%S').strftime('%d %b %y, %H:%M')}"
                            response_text += (
                                f"🆔 `{acc_id}`: `{email}` ({pass_display})\n"
                                f"Status: {status}{sold_info}{notes_info}{added_info}\n\n"
                            )
                    
                    if len(response_text) > 4096:
                        temp_fn = "daftar_akun_lengkap.txt"
                        # Hapus markdown untuk file teks agar lebih bersih
                        clean_response = response_text.replace("`", "").replace("*", "").replace("✅", "-").replace("☑️", "-").replace("🆔", "ID:").replace("📝", "Catatan:").replace("➕", "Ditambah:")
                        with open(temp_fn, "w", encoding="utf-8") as f:
                            f.write(clean_response)
                        with open(temp_fn, "rb") as f:
                            bot.send_document(chat_id, f, caption="Daftar akun terlalu panjang, dikirim sebagai file.",
                                              reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Kembali ke Menu Produk", callback_data=AdminCallbackData.BACK_TO_PRODUCT)))
                        os.remove(temp_fn)
                        bot.delete_message(chat_id, message_id)
                    else:
                        bot.edit_message_text(response_text, chat_id, message_id,
                                              reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Kembali ke Menu Produk", callback_data=AdminCallbackData.BACK_TO_PRODUCT)))
                except sqlite3.Error as e_sql:
                    logger.error(f"DB Error di AdminCallbackData.LIST_ACCOUNTS: {e_sql}", exc_info=True)
                    bot.send_message(chat_id, "❌ Gagal mengambil daftar akun dari database.")

            elif data == AdminCallbackData.CHECK_STOCK_DETAIL:
                try:
                    with sqlite3.connect(DB_NAME) as conn:
                        c = conn.cursor()
                        c.execute('SELECT id, email, password, notes, date_added FROM accounts WHERE sold = 0 ORDER BY date_added ASC, id ASC')
                        available_accounts: List[Tuple[int, str, str, Optional[str], str]] = c.fetchall()
                    
                    if not available_accounts:
                        stock_message = "📦 *Stok Akun Tersedia Saat Ini*\n\n🎉 Semua akun telah terjual atau belum ada stok."
                    else:
                        stock_message = f"📦 *Stok Akun Tersedia ({len(available_accounts)} Akun)*:\n(Urut berdasarkan tanggal ditambah, terlama dulu - akan dijual duluan)\n\n"
                        for acc_id, email, password, notes, date_added in available_accounts:
                            stock_message += f"🆔 `{acc_id}` | 📧 `{email}` | 🔑 `{password}`\n"
                            if notes: stock_message += f"   📝 {notes}\n"
                            stock_message += f"   ➕ Ditambah: {datetime.strptime(date_added, '%Y-%m-%d %H:%M:%S').strftime('%d %b %y, %H:%M')}\n---\n"
                    
                    if len(stock_message) > 4096:
                         stock_message = stock_message[:4000] + "\n\n⚠️ Data terlalu panjang, beberapa item mungkin terpotong..."
                    bot.edit_message_text(stock_message, chat_id, message_id,
                                          reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Kembali ke Menu Produk", callback_data=AdminCallbackData.BACK_TO_PRODUCT)))
                except sqlite3.Error as e_sql:
                    logger.error(f"DB Error di AdminCallbackData.CHECK_STOCK_DETAIL: {e_sql}", exc_info=True)
                    bot.send_message(chat_id, "❌ Gagal mengambil detail stok dari database.")

            elif data == AdminCallbackData.DELETE_ACCOUNT_PROMPT:
                msg_prompt = bot.edit_message_text("🗑 *Hapus Akun*\nMasukkan ID akun yang ingin dihapus (ketik /cancel untuk batal):",
                                         chat_id, message_id,
                                         reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("❌ Batal & Kembali ke Produk", callback_data=AdminCallbackData.CANCEL_BACK_PRODUCT)))
                bot.register_next_step_handler(msg_prompt, process_delete_account_admin)
            
            elif data.startswith(AdminCallbackData.CONFIRM_DELETE_ACCOUNT_PREFIX):
                handle_confirm_delete_account(call) # Dipindahkan ke fungsi terpisah

            # --- Finance Management Callbacks ---
            elif data == AdminCallbackData.PAYMENT_METHODS:
                try:
                    with sqlite3.connect(DB_NAME) as conn:
                        c = conn.cursor()
                        c.execute("SELECT id, method, number, holder_name, active FROM payment_methods ORDER BY method")
                        methods: List[Tuple[int, str, str, str, int]] = c.fetchall()
                    
                    text = "💳 *Pengaturan Metode Pembayaran*\n\n"
                    markup_pm = InlineKeyboardMarkup(row_width=1) # Tombol utama
                    action_buttons_per_method: List[InlineKeyboardButton] = [] # Tombol per metode

                    if methods:
                        text += "Metode yang terdaftar:\n"
                        for m_id, m_name, m_num, m_holder, m_active in methods:
                            status = "🟢 Aktif" if m_active else "🔴 Nonaktif"
                            text += f"\n*{m_name}* (`{m_num}` a/n {m_holder}) - {status}\n"
                            action_label = "Nonaktifkan" if m_active else "Aktifkan"
                            # Tambah tombol ke list dulu, lalu add ke markup berpasangan
                            action_buttons_per_method.append(InlineKeyboardButton(f"{action_label} {m_name} (ID: {m_id})", callback_data=f"{AdminCallbackData.TOGGLE_PAYMENT_METHOD_PREFIX}{m_id}"))
                            action_buttons_per_method.append(InlineKeyboardButton(f"🗑 Hapus {m_name} (ID: {m_id})", callback_data=f"{AdminCallbackData.DELETE_PAYMENT_METHOD_PREFIX}{m_id}"))
                    else:
                        text += "Belum ada metode pembayaran dikonfigurasi.\n"
                    
                    markup_pm.add(InlineKeyboardButton("➕ Tambah Metode Baru", callback_data=AdminCallbackData.ADD_PAYMENT_METHOD))
                    # Tambahkan tombol aksi per metode secara berpasangan
                    for i in range(0, len(action_buttons_per_method), 2):
                        if i + 1 < len(action_buttons_per_method):
                            markup_pm.add(action_buttons_per_method[i], action_buttons_per_method[i+1])
                        else:
                            markup_pm.add(action_buttons_per_method[i])
                    markup_pm.add(InlineKeyboardButton("🔙 Kembali ke Menu Keuangan", callback_data=AdminCallbackData.BACK_TO_FINANCE))
                    bot.edit_message_text(text, chat_id, message_id, reply_markup=markup_pm)
                except sqlite3.Error as e_sql:
                    logger.error(f"DB Error di AdminCallbackData.PAYMENT_METHODS: {e_sql}", exc_info=True)
                    bot.send_message(chat_id, "❌ Gagal mengambil data metode pembayaran.")

            elif data.startswith(AdminCallbackData.TOGGLE_PAYMENT_METHOD_PREFIX):
                pm_id = int(data.split('_')[-1])
                try:
                    with sqlite3.connect(DB_NAME) as conn:
                        c = conn.cursor()
                        c.execute("UPDATE payment_methods SET active = NOT active WHERE id = ?", (pm_id,))
                        conn.commit()
                        if c.rowcount > 0:
                            bot.answer_callback_query(call.id, "Status metode pembayaran diubah.")
                            # Refresh view
                            new_call_obj = call
                            new_call_obj.data = AdminCallbackData.PAYMENT_METHODS 
                            handle_admin_callback(new_call_obj)
                        else:
                            bot.answer_callback_query(call.id, "Metode tidak ditemukan.")
                except sqlite3.Error as e_sql:
                    logger.error(f"DB error toggle payment method {pm_id}: {e_sql}", exc_info=True)
                    bot.answer_callback_query(call.id, "Error database.")

            elif data.startswith(AdminCallbackData.DELETE_PAYMENT_METHOD_PREFIX):
                pm_id_to_delete = int(data.split('_')[-1])
                confirm_markup = InlineKeyboardMarkup(row_width=1)
                confirm_markup.add(InlineKeyboardButton(f"✅ Ya, Hapus Metode ID {pm_id_to_delete}", callback_data=f"{AdminCallbackData.CONFIRM_DELETE_PAYMENT_METHOD_PREFIX}{pm_id_to_delete}"))
                confirm_markup.add(InlineKeyboardButton("❌ Tidak, Batalkan", callback_data=AdminCallbackData.PAYMENT_METHODS))
                bot.edit_message_text(f"❓ Anda yakin ingin menghapus metode pembayaran dengan ID `{pm_id_to_delete}`? Tindakan ini tidak dapat diurungkan.",
                                      chat_id, message_id, reply_markup=confirm_markup)

            elif data.startswith(AdminCallbackData.CONFIRM_DELETE_PAYMENT_METHOD_PREFIX):
                pm_id_really_delete = int(data.split('_')[-1])
                try:
                    with sqlite3.connect(DB_NAME) as conn:
                        c = conn.cursor()
                        c.execute("DELETE FROM payment_methods WHERE id = ?", (pm_id_really_delete,))
                        conn.commit()
                        if c.rowcount > 0:
                            bot.answer_callback_query(call.id, f"Metode pembayaran ID {pm_id_really_delete} dihapus.")
                            new_call_obj = call
                            new_call_obj.data = AdminCallbackData.PAYMENT_METHODS
                            handle_admin_callback(new_call_obj)
                        else:
                            bot.answer_callback_query(call.id, "Metode tidak ditemukan/sudah dihapus.")
                            bot.edit_message_text(f"Metode pembayaran ID {pm_id_really_delete} tidak ditemukan.", chat_id, message_id,
                                                  reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Kembali", callback_data=AdminCallbackData.PAYMENT_METHODS)))
                except sqlite3.Error as e_sql:
                    logger.error(f"DB error menghapus payment method {pm_id_really_delete}: {e_sql}", exc_info=True)
                    bot.answer_callback_query(call.id, "Error database saat menghapus.")
            
            elif data == AdminCallbackData.ADD_PAYMENT_METHOD:
                msg_prompt = bot.edit_message_text(
                    "➕ *Tambah Metode Pembayaran Baru*\nFormat: `NAMA_METODE|NOMOR|NAMA_PEMILIK`\nContoh: `DANA|08123xxxx|John Doe`\n\nMetode umum: "
                    f"{', '.join(PAYMENT_METHODS) if PAYMENT_METHODS else 'DANA, OVO, GOPAY, dll.'}\n\nKetik /cancel untuk batal.",
                    chat_id, message_id,
                    reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("❌ Batal & Kembali ke Keuangan", callback_data=AdminCallbackData.CANCEL_BACK_FINANCE)))
                bot.register_next_step_handler(msg_prompt, process_add_payment_method_admin)

            elif data == AdminCallbackData.PRICE_SETTINGS:
                current_price_raw = get_setting('price')
                current_price_formatted = format_rupiah(current_price_raw)
                msg_prompt = bot.edit_message_text(
                    f"💲 *Pengaturan Harga Akun*\nHarga saat ini: *{current_price_formatted}*\n\nMasukkan harga baru (angka saja, misal `50000`):\n\nKetik /cancel untuk batal.",
                    chat_id, message_id,
                    reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("❌ Batal & Kembali ke Keuangan", callback_data=AdminCallbackData.CANCEL_BACK_FINANCE)))
                bot.register_next_step_handler(msg_prompt, process_price_settings_admin)

            elif data == AdminCallbackData.SALES_REPORT:
                try:
                    with sqlite3.connect(DB_NAME) as conn:
                        c = conn.cursor()
                        thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S')
                        c.execute("""
                            SELECT s.id, s.buyer_username, s.buyer_id, s.amount, s.payment_method, s.status, s.completed_date, a.email, s.admin_notes
                            FROM sales s
                            LEFT JOIN accounts a ON s.account_id = a.id
                            WHERE (s.status = 'completed' OR s.status = 'cancelled') AND s.created_date >= ? 
                            ORDER BY s.completed_date DESC, s.created_date DESC
                        """, (thirty_days_ago,)) # Menampilkan completed dan cancelled
                        sales_data: List[Tuple[int, Optional[str], int, str, Optional[str], str, Optional[str], Optional[str], Optional[str]]] = c.fetchall()

                    report_text = f"📊 *Laporan Transaksi (30 Hari Terakhir)*\n\n"
                    if not sales_data:
                        report_text += "Tidak ada transaksi dalam 30 hari terakhir."
                    else:
                        total_sales_amount = 0.0
                        for sale_id, username, buyer_id, amount_str, payment, status, date_completed, acc_email, admin_notes_val in sales_data:
                            try:
                                amount = float(str(amount_str).replace('.', '').replace(',', '')) if status == 'completed' else 0.0
                                if status == 'completed': total_sales_amount += amount
                            except ValueError:
                                amount = 0.0
                                report_text += f"⚠️ Format jumlah salah untuk Sale ID {sale_id}\n"

                            buyer_name_display = username if username and username != f"user_{buyer_id}" else f"User ID {buyer_id}"
                            buyer_contact = f"@{username}" if username and username != f"user_{buyer_id}" else f"ID: {buyer_id}"
                            
                            report_text += (
                                f"🆔 Transaksi: `{sale_id}`\n"
                                f"👤 Pembeli: {buyer_contact}\n"
                                f"状态 Status: *{status.upper()}*\n" # Menggunakan Bahasa Mandarin untuk 'Status' sebagai contoh variasi (bisa diganti)
                                f"📧 Akun: `{acc_email if acc_email else 'N/A (jika pending/cancelled tanpa akun)'}`\n"
                                f"💰 Jumlah: {format_rupiah(amount) if status == 'completed' else '-'}\n"
                                f"💳 Metode Bayar (User): {payment if payment else 'N/A'}\n" # Ini adalah metode yang mungkin dipilih user, bukan metode toko
                                f"🗓 Tgl Selesai/Batal: {datetime.strptime(date_completed, '%Y-%m-%d %H:%M:%S').strftime('%d %b %y, %H:%M') if date_completed else 'N/A'}\n"
                            )
                            if status == 'cancelled' and admin_notes_val:
                                report_text += f"📝 Catatan Admin: {admin_notes_val}\n"
                            report_text += "--------------------\n"
                        report_text += f"\n*Total Pendapatan Sukses (30 Hari): {format_rupiah(total_sales_amount)}*"
                    
                    if len(report_text) > 4096:
                        report_text = report_text[:4000] + "\n\n⚠️ Laporan terlalu panjang..."
                    
                    bot.edit_message_text(report_text, chat_id, message_id,
                                          reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Kembali ke Menu Keuangan", callback_data=AdminCallbackData.BACK_TO_FINANCE)))
                except sqlite3.Error as e_sql:
                    logger.error(f"DB Error di AdminCallbackData.SALES_REPORT: {e_sql}", exc_info=True)
                    bot.send_message(chat_id, "❌ Gagal mengambil laporan penjualan dari database.")
                except Exception as e_gen:
                    logger.error(f"Error membuat laporan penjualan: {e_gen}", exc_info=True)
                    bot.send_message(chat_id, "❌ Error internal saat membuat laporan penjualan.")

            elif data == AdminCallbackData.PENDING_PAYMENTS_MENU:
                display_pending_payments_admin(chat_id, message_id_to_edit=message_id)

            # --- Settings Callbacks ---
            elif data == AdminCallbackData.TOGGLE_MAINTENANCE:
                current_mode = get_setting('maintenance_mode')
                new_mode = 'off' if current_mode == 'on' else 'on'
                if set_setting('maintenance_mode', new_mode):
                    status_text = "ON 🟢" if new_mode == 'on' else "OFF 🔴"
                    bot.answer_callback_query(call.id, f"Mode Maintenance: {status_text.split(' ')[0]}")
                    
                    # Update original settings message
                    updated_markup = InlineKeyboardMarkup(row_width=1)
                    updated_markup.add(
                        InlineKeyboardButton(f"🛠 Mode Maintenance: {status_text}", callback_data=AdminCallbackData.TOGGLE_MAINTENANCE),
                        InlineKeyboardButton("💲 Atur Harga Akun", callback_data=AdminCallbackData.PRICE_SETTINGS),
                        InlineKeyboardButton("💳 Metode Pembayaran", callback_data=AdminCallbackData.PAYMENT_METHODS)
                    )
                    current_price = format_rupiah(get_setting('price'))
                    settings_text_updated = (
                        f"⚙️ *Pengaturan Bot - {STORE_NAME}*\n\n"
                        f"Harga Saat Ini: `{current_price}`\n"
                        f"Mode Maintenance: `{status_text}`\n\nPilih pengaturan:"
                    )
                    try:
                        bot.edit_message_text(settings_text_updated, chat_id, message_id, reply_markup=updated_markup)
                    except telebot.apihelper.ApiTelegramException as e_edit:
                         if "message is not modified" not in str(e_edit).lower(): logger.error(f"Error edit pesan pengaturan: {e_edit}")
                else:
                    bot.answer_callback_query(call.id, "❌ Gagal ubah mode maintenance.")
            
            # --- Cancellation & Navigation Callbacks ---
            elif data == AdminCallbackData.CANCEL_ACTION:
                try:
                    bot.edit_message_text("ℹ️ Tindakan dibatalkan.", chat_id, message_id, reply_markup=None)
                except telebot.apihelper.ApiTelegramException as e_edit:
                    if any(err_str in str(e_edit).lower() for err_str in ["message to edit not found", "message can't be edited"]):
                        bot.send_message(chat_id, "ℹ️ Tindakan dibatalkan. (Pesan sebelumnya tidak bisa diedit)")
                    elif "message is not modified" not in str(e_edit).lower():
                         logger.warning(f"AdminCallbackData.CANCEL_ACTION edit gagal: {e_edit}")

            elif data == AdminCallbackData.CANCEL_BACK_PRODUCT:
                bot.answer_callback_query(call.id, "Dibatalkan.")
                new_call_obj = call 
                new_call_obj.data = AdminCallbackData.BACK_TO_PRODUCT
                handle_admin_callback(new_call_obj)

            elif data == AdminCallbackData.CANCEL_BACK_FINANCE:
                bot.answer_callback_query(call.id, "Dibatalkan.")
                new_call_obj = call
                new_call_obj.data = AdminCallbackData.BACK_TO_FINANCE
                handle_admin_callback(new_call_obj)

            elif data == AdminCallbackData.BACK_TO_PRODUCT:
                markup_prod = InlineKeyboardMarkup(row_width=2)
                markup_prod.add(
                    InlineKeyboardButton("➕ Tambah Akun", callback_data=AdminCallbackData.ADD_ACCOUNT),
                    InlineKeyboardButton("📋 List Semua Akun", callback_data=AdminCallbackData.LIST_ACCOUNTS),
                    InlineKeyboardButton("📦 Stok Tersedia (Detail)", callback_data=AdminCallbackData.CHECK_STOCK_DETAIL),
                    InlineKeyboardButton("🗑 Hapus Akun", callback_data=AdminCallbackData.DELETE_ACCOUNT_PROMPT)
                )
                bot.edit_message_text("📦 *Menu Manajemen Produk*\n\nPilih tindakan:", chat_id, message_id, reply_markup=markup_prod)

            elif data == AdminCallbackData.BACK_TO_FINANCE:
                markup_fin = InlineKeyboardMarkup(row_width=2)
                markup_fin.add(
                    InlineKeyboardButton("💳 Metode Pembayaran", callback_data=AdminCallbackData.PAYMENT_METHODS),
                    InlineKeyboardButton("💲 Atur Harga Akun", callback_data=AdminCallbackData.PRICE_SETTINGS),
                    InlineKeyboardButton("📊 Laporan Penjualan", callback_data=AdminCallbackData.SALES_REPORT),
                    InlineKeyboardButton("⏳ Pembayaran Pending", callback_data=AdminCallbackData.PENDING_PAYMENTS_MENU)
                )
                bot.edit_message_text("💰 *Menu Manajemen Keuangan*\n\nPilih tindakan:", chat_id, message_id, reply_markup=markup_fin)

        except telebot.apihelper.ApiTelegramException as e_api:
            err_msg_lower = str(e_api).lower()
            if any(err_str in err_msg_lower for err_str in ["message to edit not found", "message can't be edited", "message is not modified"]):
                logger.warning(f"API Exception di admin callback (data: {data}): {e_api}. Pesan mungkin terlalu lama atau sudah ditangani.")
                if "not modified" not in err_msg_lower:
                     bot.send_message(chat_id, "Sesi menu sebelumnya mungkin sudah kedaluwarsa. Silakan ulangi dari menu utama.")
            else:
                logger.error(f"API Error di handle_admin_callback (data: {data}): {e_api}", exc_info=True)
                bot.send_message(chat_id, "❌ Terjadi kesalahan API Telegram. Coba lagi dari menu utama.")
        except Exception as e:
            logger.error(f"Error di handle_admin_callback (data: {data}): {e}", exc_info=True)
            bot.send_message(chat_id, "❌ Terjadi kesalahan internal. Silakan coba lagi dari menu utama atau hubungi developer jika berlanjut.")

    # --- Process Functions for Admin (called by next_step_handler) ---
    def process_add_account_admin(message: Message) -> None:
        """Memproses input untuk menambah akun baru."""
        if not is_admin(message.from_user.id): return
        if message.text == '/cancel':
            bot.reply_to(message, "Penambahan akun dibatalkan. Silakan gunakan menu lagi.")
            return
        
        parts = message.text.split('|')
        if not (2 <= len(parts) <= 3):
            msg_retry = bot.reply_to(message, "❌ Format salah! `email|password` atau `email|password|catatan`\nKetik /cancel atau coba lagi.")
            bot.register_next_step_handler(msg_retry, process_add_account_admin)
            return
        
        email, password = parts[0].strip(), parts[1].strip()
        notes = parts[2].strip() if len(parts) == 3 else ""

        if '@' not in email or '.' not in email.split('@')[-1] or not password: # Validasi email sederhana
            msg_retry = bot.reply_to(message, "❌ Email atau Password tidak valid. Coba lagi atau /cancel.")
            bot.register_next_step_handler(msg_retry, process_add_account_admin)
            return

        try:
            with sqlite3.connect(DB_NAME) as conn:
                c = conn.cursor()
                c.execute('SELECT id FROM accounts WHERE email = ?', (email,))
                if c.fetchone():
                    msg_retry = bot.reply_to(message, "❌ Email sudah ada di database. Gunakan email lain atau /cancel.")
                    bot.register_next_step_handler(msg_retry, process_add_account_admin)
                    return
                
                date_added_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                c.execute('INSERT INTO accounts (email, password, notes, date_added) VALUES (?, ?, ?, ?)',
                          (email, password, notes, date_added_str))
                new_id = c.lastrowid
                conn.commit()
                c.execute('SELECT COUNT(*) FROM accounts WHERE sold = 0')
                stock = c.fetchone()[0]
            bot.reply_to(message, f"✅ Akun ID `{new_id}` (Email: `{email}`) berhasil ditambahkan.\nStok tersedia saat ini: {stock} akun.")
        except sqlite3.IntegrityError: # Email unique constraint failed (double check, seharusnya sudah ditangani di atas)
            msg_retry = bot.reply_to(message, "❌ Email sudah ada (Integrity Error). Coba lagi atau /cancel.")
            bot.register_next_step_handler(msg_retry, process_add_account_admin)
        except sqlite3.Error as e_sql:
            logger.error(f"DB error menambah akun: {e_sql}", exc_info=True)
            msg_retry = bot.reply_to(message, "❌ Error database saat menambah akun. Coba lagi atau /cancel.")
            bot.register_next_step_handler(msg_retry, process_add_account_admin)

    def process_delete_account_admin(message: Message) -> None:
        """Memproses input ID akun yang akan dihapus."""
        if not is_admin(message.from_user.id): return
        if message.text == '/cancel':
            bot.reply_to(message, "Penghapusan akun dibatalkan. Silakan gunakan menu lagi.")
            return
        try:
            acc_id_del = int(message.text.strip())
            with sqlite3.connect(DB_NAME) as conn:
                c = conn.cursor()
                c.execute("SELECT email, sold FROM accounts WHERE id = ?", (acc_id_del,))
                account_data = c.fetchone()
            if not account_data:
                msg_retry = bot.reply_to(message, f"❌ Akun ID `{acc_id_del}` tidak ditemukan. /cancel atau masukkan ID lain.")
                bot.register_next_step_handler(msg_retry, process_delete_account_admin)
                return
            
            email_to_delete, sold_status = account_data
            status_info = "(SUDAH TERJUAL)" if sold_status == 1 else "(TERSEDIA)"
            # Menggunakan AdminCallbackData.CONFIRM_DELETE_ACCOUNT_PREFIX
            markup = InlineKeyboardMarkup(row_width=1).add(
                InlineKeyboardButton(f"✅ Ya, Hapus ID {acc_id_del}", callback_data=f"{AdminCallbackData.CONFIRM_DELETE_ACCOUNT_PREFIX}{acc_id_del}"),
                InlineKeyboardButton("❌ Tidak, Batal & Kembali", callback_data=AdminCallbackData.CANCEL_BACK_PRODUCT)
            )
            bot.reply_to(message, f"Yakin ingin menghapus akun ID `{acc_id_del}` (Email: `{email_to_delete}`) {status_info}?\nData penjualan terkait akan diupdate (akun_id menjadi NULL jika `ON DELETE SET NULL` aktif).",
                         reply_markup=markup)
        except ValueError:
            msg_retry = bot.reply_to(message, "❌ ID akun harus berupa angka. /cancel atau masukkan ID lain.")
            bot.register_next_step_handler(msg_retry, process_delete_account_admin)
        except sqlite3.Error as e_sql:
            logger.error(f"DB error saat prompt hapus akun: {e_sql}", exc_info=True)
            bot.reply_to(message, "❌ Error database. Coba lagi nanti.")

    # Handler untuk konfirmasi hapus akun (dipanggil dari handle_admin_callback)
    def handle_confirm_delete_account(call: CallbackQuery) -> None:
        """Menangani konfirmasi penghapusan akun."""
        # Diasumsikan user_id sudah dicek admin di handle_admin_callback
        account_id_to_delete = int(call.data.split(AdminCallbackData.CONFIRM_DELETE_ACCOUNT_PREFIX)[-1])
        chat_id = call.message.chat.id
        message_id = call.message.message_id

        try:
            with sqlite3.connect(DB_NAME) as conn:
                c = conn.cursor()
                c.execute("SELECT email FROM accounts WHERE id = ?", (account_id_to_delete,))
                email_deleted_tuple = c.fetchone()
                if not email_deleted_tuple:
                    bot.edit_message_text(f"⚠️ Akun ID `{account_id_to_delete}` sudah tidak ada atau salah ID.", chat_id, message_id)
                    bot.answer_callback_query(call.id, "Akun tidak ditemukan.")
                    return

                # PRAGMA foreign_keys = ON sudah diatur di init_db dan koneksi, ON DELETE SET NULL akan bekerja
                c.execute("DELETE FROM accounts WHERE id = ?", (account_id_to_delete,))
                conn.commit()

                if c.rowcount > 0:
                    bot.edit_message_text(f"✅ Akun ID `{account_id_to_delete}` (Email: `{email_deleted_tuple[0]}`) berhasil dihapus.", chat_id, message_id,
                                          reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Kembali ke Menu Produk", callback_data=AdminCallbackData.BACK_TO_PRODUCT)))
                    bot.answer_callback_query(call.id, "Akun berhasil dihapus.")
                else: # Seharusnya sudah ditangani oleh cek email_deleted_tuple
                    bot.edit_message_text(f"⚠️ Akun ID `{account_id_to_delete}` tidak ditemukan saat mencoba menghapus.", chat_id, message_id)
                    bot.answer_callback_query(call.id, "Akun tidak ditemukan.")
        except sqlite3.IntegrityError as e_int: # Jika ON DELETE RESTRICT/NO ACTION (seharusnya tidak dengan SET NULL)
            logger.error(f"DB IntegrityError saat hapus akun {account_id_to_delete}: {e_int}", exc_info=True)
            bot.edit_message_text(f"❌ Gagal hapus ID `{account_id_to_delete}`. Akun ini mungkin masih terkait dengan data penjualan yang tidak bisa di-NULL-kan.", chat_id, message_id,
                                  reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Kembali ke Menu Produk", callback_data=AdminCallbackData.BACK_TO_PRODUCT)))
            bot.answer_callback_query(call.id, "Gagal hapus, terkait data lain.")
        except sqlite3.Error as e_sql:
            logger.error(f"DB error saat konfirmasi hapus akun {account_id_to_delete}: {e_sql}", exc_info=True)
            bot.edit_message_text("❌ Error database saat menghapus akun.", chat_id, message_id)
            bot.answer_callback_query(call.id, "Error database.")
        except Exception as e_gen:
            logger.error(f"Error tak terduga saat konfirmasi hapus akun {account_id_to_delete}: {e_gen}", exc_info=True)
            bot.edit_message_text("❌ Error tak terduga.", chat_id, message_id)
            bot.answer_callback_query(call.id, "Error tak terduga.")
    
    def process_add_payment_method_admin(message: Message) -> None:
        """Memproses input untuk menambah metode pembayaran baru."""
        if not is_admin(message.from_user.id): return
        if message.text == '/cancel':
            bot.reply_to(message, "Penambahan metode pembayaran dibatalkan. Silakan gunakan menu lagi.")
            return
        
        parts = message.text.split('|')
        if len(parts) != 3:
            msg_retry = bot.reply_to(message, "❌ Format salah! `NAMA_METODE|NOMOR|NAMA_PEMILIK`\nKetik /cancel atau coba lagi.")
            bot.register_next_step_handler(msg_retry, process_add_payment_method_admin)
            return

        method_name, acc_number, holder_name = parts[0].strip().upper(), parts[1].strip(), parts[2].strip()
        if not all([method_name, acc_number, holder_name]):
            msg_retry = bot.reply_to(message, "❌ Semua field (Nama Metode, Nomor, Nama Pemilik) harus diisi. /cancel atau coba lagi.")
            bot.register_next_step_handler(msg_retry, process_add_payment_method_admin)
            return
        
        try:
            with sqlite3.connect(DB_NAME) as conn:
                c = conn.cursor()
                # INSERT OR REPLACE akan update jika method sudah ada, atau insert baru
                c.execute('''INSERT OR REPLACE INTO payment_methods (method, number, holder_name, active)
                             VALUES (?, ?, ?, 1)''', (method_name, acc_number, holder_name))
                conn.commit()
            bot.reply_to(message, f"✅ Metode pembayaran '{method_name}' berhasil ditambahkan/diperbarui dan diaktifkan.")
            # Bisa tambahkan tombol untuk kembali ke menu keuangan
        except sqlite3.Error as e_sql:
            logger.error(f"DB error menambah/update metode pembayaran: {e_sql}", exc_info=True)
            msg_retry = bot.reply_to(message, "❌ Error database. /cancel atau coba lagi.")
            bot.register_next_step_handler(msg_retry, process_add_payment_method_admin)

    def process_price_settings_admin(message: Message) -> None:
        """Memproses input untuk mengubah harga akun."""
        if not is_admin(message.from_user.id): return
        if message.text == '/cancel':
            bot.reply_to(message, "Pengaturan harga dibatalkan. Silakan gunakan menu lagi.")
            return
        
        new_price_input = message.text.strip().replace('.', '').replace(',', '') # Bersihkan input harga
        try:
            if not new_price_input.isdigit(): raise ValueError("Harga harus berupa angka.")
            price_value = int(new_price_input)
            if price_value <= 0: raise ValueError("Harga harus lebih dari 0.")
            
            if set_setting('price', str(price_value)):
                bot.reply_to(message, f"✅ Harga akun berhasil diubah menjadi: *{format_rupiah(str(price_value))}*")
            else:
                raise Exception("Gagal menyimpan harga ke database.") # Akan ditangkap oleh blok except umum
        except ValueError as ve:
            msg_retry = bot.reply_to(message, f"❌ Format harga salah: {ve}\nMasukkan angka positif saja (misal `50000`). /cancel atau coba lagi.")
            bot.register_next_step_handler(msg_retry, process_price_settings_admin)
        except Exception as e:
            logger.error(f"Error saat mengatur harga: {e}", exc_info=True)
            msg_retry = bot.reply_to(message, "❌ Gagal menyimpan harga. /cancel atau coba lagi.")
            bot.register_next_step_handler(msg_retry, process_price_settings_admin)

    # --- ADMIN /approve DAN /reject COMMANDS ---
    @bot.message_handler(commands=['approve'])
    def approve_payment_command(message: Message) -> None:
        """Menyetujui pembayaran dan mengirim akun."""
        if not is_admin(message.from_user.id):
            bot.reply_to(message, "⛔ Anda tidak punya izin untuk perintah ini.")
            return
            
        args = message.text.split()
        if len(args) < 2:
            bot.reply_to(message, "⚠️ Format: `/approve <ID_SALE>`\nContoh: `/approve 123`")
            return

        try:
            sale_id_to_approve = int(args[1])
        except ValueError:
            bot.reply_to(message, "⚠️ ID Sale harus berupa angka.")
            return

        conn: Optional[sqlite3.Connection] = None
        try:
            conn = sqlite3.connect(DB_NAME)
            conn.execute('PRAGMA foreign_keys = ON;')
            c = conn.cursor()
            
            # --- Mulai Transaksi (implisit oleh SQLite, diakhiri dengan commit/rollback) ---
            c.execute("SELECT id, account_id, buyer_id, buyer_username, status, amount FROM sales WHERE id = ?", (sale_id_to_approve,))
            sale_record = c.fetchone()

            if not sale_record:
                bot.reply_to(message, f"❌ Sale ID `{sale_id_to_approve}` tidak ditemukan.")
                return # Tidak ada DML, jadi tidak perlu rollback eksplisit
            
            _sale_id, current_account_id, buyer_tg_id, buyer_username, sale_status, sale_amount = sale_record

            if sale_status != 'pending':
                bot.reply_to(message, f"❌ Sale ID `{sale_id_to_approve}` statusnya `{sale_status.upper()}`, bukan 'pending'. Tidak bisa diproses.")
                return

            assigned_account_id = current_account_id
            acc_email, acc_pass, acc_notes = None, None, None

            if assigned_account_id is None: # Akun belum ter-assign, cari yang tersedia
                c.execute("SELECT id, email, password, notes FROM accounts WHERE sold = 0 ORDER BY date_added ASC, id ASC LIMIT 1")
                available_account = c.fetchone()
                if not available_account:
                    bot.reply_to(message, f"⚠️ *STOK HABIS!* Tidak ada akun tersedia untuk Sale ID `{sale_id_to_approve}`. Pembayaran belum bisa disetujui.\nSegera tambah stok!")
                    return # Sale tetap pending, tidak ada rollback diperlukan
                assigned_account_id, acc_email, acc_pass, acc_notes = available_account
                c.execute("UPDATE sales SET account_id = ? WHERE id = ?", (assigned_account_id, sale_id_to_approve)) # DML 1
            else: # Akun sudah ter-assign, fetch detailnya
                c.execute("SELECT email, password, notes, sold FROM accounts WHERE id = ?", (assigned_account_id,))
                account_data = c.fetchone()
                if not account_data:
                    bot.reply_to(message, f"❌ Error: Akun ID `{assigned_account_id}` (terhubung ke Sale ID `{sale_id_to_approve}`) tidak ditemukan di database. Mungkin terhapus.")
                    c.execute("UPDATE sales SET status = 'failed', admin_notes = ? WHERE id = ?", 
                              (f"Gagal approve: Akun ID {assigned_account_id} tidak ditemukan saat approval.", sale_id_to_approve))
                    conn.commit() # Commit status 'failed' ini
                    return
                acc_email, acc_pass, acc_notes, acc_already_sold = account_data
                if acc_already_sold == 1:
                    bot.reply_to(message, f"⚠️ *PERINGATAN:* Akun ID `{assigned_account_id}` (Email: `{acc_email}`) untuk Sale ID `{sale_id_to_approve}` SUDAH TERJUAL sebelumnya. Harap periksa manual untuk hindari duplikasi penjualan!\nApproval dibatalkan. Periksa dan `/approve` lagi jika aman.")
                    return

            now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            c.execute('''UPDATE accounts 
                         SET sold = 1, sold_to_username = ?, sold_to_id = ?, sold_date = ?
                         WHERE id = ? AND sold = 0''', # Kunci: AND sold = 0
                      (buyer_username, buyer_tg_id, now_str, assigned_account_id)) # DML 2
            
            if c.rowcount == 0: # Jika akun gagal diupdate (misal, sudah terjual oleh proses lain)
                bot.reply_to(message, f"❌ *GAGAL UPDATE AKUN!* Akun ID `{assigned_account_id}` tidak bisa ditandai terjual (mungkin sudah terjual oleh proses lain atau tidak valid). Approval dibatalkan. Periksa dan coba lagi.")
                logger.error(f"Kondisi kritis atau race condition saat menandai akun {assigned_account_id} terjual untuk sale {sale_id_to_approve}. Rowcount 0 pada update akun.")
                conn.rollback() # Rollback semua perubahan (termasuk update sales.account_id jika terjadi)
                return 

            c.execute("UPDATE sales SET status = 'completed', completed_date = ? WHERE id = ?", (now_str, sale_id_to_approve)) # DML 3
            
            conn.commit() # --- COMMIT TRANSAKSI ---
            
            # Kirim detail akun ke pembeli
            account_details_text = (
                f"🎉 *Pembayaran Anda (Sale ID: `{sale_id_to_approve}`) Telah Disetujui! ({STORE_NAME})*\n\n"
                f"Berikut detail akun Blackbox.ai Anda:\n"
                f"📧 Email: `{acc_email}`\n"
                f"🔑 Password: `{acc_pass}`"
            )
            if acc_notes: account_details_text += f"\n📝 Catatan: {acc_notes}"
            account_details_text += (
                f"\n\n*⚠️ PENTING:*\n"
                f"  • Segera amankan akun (ganti password jika disarankan).\n"
                f"  • Simpan detail ini baik-baik.\n"
                f"  • Jika ada kendala login awal, hubungi Admin @{ADMIN_USERNAME} (sertakan screenshot).\n\n"
                f"Terima kasih telah bertransaksi di {STORE_NAME}! 😊"
            )
            
            buyer_notified_successfully = False
            if buyer_tg_id:
                try:
                    bot.send_message(buyer_tg_id, account_details_text)
                    buyer_notified_successfully = True
                except Exception as e_send:
                    logger.error(f"Gagal kirim detail akun ke buyer {buyer_tg_id} (Sale {sale_id_to_approve}): {e_send}")
            else:
                logger.warning(f"Tidak ada buyer_tg_id untuk Sale ID {sale_id_to_approve}, tidak bisa kirim detail otomatis.")

            admin_feedback = (
                f"✅ *Pembayaran Berhasil Disetujui & Akun Terkirim!*\n\n"
                f"Sale ID: `{sale_id_to_approve}`\n"
                f"Pembeli: @{buyer_username if buyer_username and buyer_username != f'user_{buyer_tg_id}' else f'ID {buyer_tg_id}'}\n"
                f"Akun ID: `{assigned_account_id}` (Email: `{acc_email}`)\n"
            )
            if buyer_notified_successfully:
                admin_feedback += "Detail akun telah dikirim ke pembeli."
            else:
                admin_feedback += f"⚠️ *PENTING*: Detail akun GAGAL dikirim otomatis ke pembeli. Mohon KIRIM MANUAL ke @{buyer_username if buyer_username and buyer_username != f'user_{buyer_tg_id}' else (f'ID {buyer_tg_id}' if buyer_tg_id else 'ID TIDAK DIKETAHUI')}."
            bot.reply_to(message, admin_feedback)

        except sqlite3.Error as e_sql:
            logger.error(f"Kesalahan database pada approve_payment untuk Sale ID {args[1] if len(args)>1 else 'N/A'}: {e_sql}", exc_info=True)
            bot.reply_to(message, "❌ Terjadi kesalahan database. Perubahan telah dibatalkan (rollback).")
            if conn: conn.rollback()
        except Exception as e_main:
            logger.error(f"Kesalahan tak terduga pada approve_payment untuk Sale ID {args[1] if len(args)>1 else 'N/A'}: {e_main}", exc_info=True)
            bot.reply_to(message, "❌ Terjadi kesalahan tak terduga. Perubahan mungkin telah dibatalkan (rollback).")
            if conn:
                try: conn.rollback()
                except Exception: pass # Abaikan jika rollback juga gagal
        finally:
            if conn: conn.close()

    @bot.message_handler(commands=['reject'])
    def reject_payment_command(message: Message) -> None:
        """Membatalkan pembayaran yang pending."""
        if not is_admin(message.from_user.id):
            bot.reply_to(message, "⛔ Anda tidak punya izin untuk perintah ini.")
            return

        args = message.text.split(maxsplit=2) # /reject SALE_ID ALASAN_PANJANG
        if len(args) < 2:
            bot.reply_to(message, "⚠️ Format: `/reject <ID_SALE> [ALASAN]`\nContoh: `/reject 123 Bukti tidak valid`")
            return

        try:
            sale_id_to_reject = int(args[1])
            rejection_reason = args[2].strip() if len(args) > 2 else "Tidak ada alasan spesifik dari admin."
        except ValueError:
            bot.reply_to(message, "⚠️ ID Sale harus berupa angka.")
            return
        
        if not rejection_reason: rejection_reason = "Tidak ada alasan spesifik dari admin."


        conn: Optional[sqlite3.Connection] = None
        try:
            conn = sqlite3.connect(DB_NAME)
            conn.execute('PRAGMA foreign_keys = ON;')
            c = conn.cursor()

            c.execute("SELECT buyer_id, buyer_username, status, account_id FROM sales WHERE id = ?", (sale_id_to_reject,))
            sale_record = c.fetchone()

            if not sale_record:
                bot.reply_to(message, f"❌ Sale ID `{sale_id_to_reject}` tidak ditemukan.")
                return

            buyer_tg_id, buyer_username, sale_status, _ = sale_record # account_id tidak penting untuk reject

            if sale_status != 'pending':
                bot.reply_to(message, f"❌ Sale ID `{sale_id_to_reject}` statusnya `{sale_status.upper()}`, bukan 'pending'. Tidak dapat dibatalkan.")
                return

            now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            c.execute("UPDATE sales SET status = 'cancelled', completed_date = ?, admin_notes = ? WHERE id = ?",
                      (now_str, rejection_reason, sale_id_to_reject))
            conn.commit() # Commit perubahan status

            user_rejection_message = (
                f"ℹ️ Pembelian Anda (Sale ID: `{sale_id_to_reject}`) di {STORE_NAME} telah *DIBATALKAN* oleh admin.\n\n"
                f"Alasan: {rejection_reason}\n\n"
                f"Jika ada pertanyaan lebih lanjut, silakan hubungi @{ADMIN_USERNAME}."
            )
            notif_ke_user_gagal = False
            if buyer_tg_id:
                try:
                    bot.send_message(buyer_tg_id, user_rejection_message)
                except Exception as e_send_user:
                    logger.error(f"Gagal mengirim notifikasi pembatalan ke user {buyer_tg_id} (Sale ID {sale_id_to_reject}): {e_send_user}")
                    notif_ke_user_gagal = True
            
            admin_feedback = f"✅ Sale ID `{sale_id_to_reject}` telah berhasil dibatalkan (status: cancelled).\nAlasan: {rejection_reason}\n"
            if notif_ke_user_gagal:
                admin_feedback += f"Peringatan: Gagal memberitahu user @{buyer_username if buyer_username and buyer_username != f'user_{buyer_tg_id}' else f'ID {buyer_tg_id}'} tentang pembatalan."
            else:
                admin_feedback += "Pengguna telah (atau akan dicoba) diberitahu."
            bot.reply_to(message, admin_feedback)

        except sqlite3.Error as e_sql:
            logger.error(f"Kesalahan database pada reject_payment untuk Sale ID {sale_id_to_reject}: {e_sql}", exc_info=True)
            bot.reply_to(message, "❌ Terjadi kesalahan database saat membatalkan. Perubahan mungkin telah dibatalkan (rollback).")
            if conn: conn.rollback()
        except Exception as e_main:
            logger.error(f"Kesalahan tak terduga pada reject_payment untuk Sale ID {sale_id_to_reject}: {e_main}", exc_info=True)
            bot.reply_to(message, "❌ Terjadi kesalahan tak terduga saat membatalkan. Perubahan mungkin telah dibatalkan (rollback).")
            if conn:
                try: conn.rollback()
                except Exception: pass
        finally:
            if conn: conn.close()

    # Fallback untuk pesan teks yang tidak dikenali (opsional, bisa di-uncomment)
    # @bot.message_handler(func=lambda message: True)
    # @check_maintenance
    # def echo_all(message: Message) -> None:
    #     if is_admin(message.from_user.id):
    #         bot.reply_to(message, f"Admin: Perintah '{message.text}' tidak dikenal. Gunakan tombol menu atau /start.")
    #     else:
    #         bot.reply_to(message, f"Maaf, perintah '{message.text}' tidak saya mengerti. Silakan gunakan tombol menu atau ketik /start.")

    # Jalankan bot
    logger.info(f"Bot {STORE_NAME} (Enhanced) mulai polling...")
    init_db() # Pastikan DB diinisialisasi sebelum polling
    logger.info(f"Admin ID adalah: {ADMIN_ID} (tipe: {type(ADMIN_ID)})")
    
    polling_logger_level = logging.DEBUG if os.getenv('BOT_DEBUG_POLLING', 'false').lower() == 'true' else logging.INFO
    bot.infinity_polling(logger_level=polling_logger_level, timeout=60, long_polling_timeout=30)

except ValueError as ve_config: # Untuk error konfigurasi
    logger.critical(f"Kesalahan konfigurasi: {ve_config}", exc_info=True)
    print(f"KRITIKAL: Kesalahan konfigurasi - {ve_config}")
except Exception as e_startup: # Untuk error startup lainnya
    logger.critical(f"Gagal memulai bot: {e_startup}", exc_info=True)
    print(f"KRITIKAL: Gagal memulai bot - {e_startup}")
