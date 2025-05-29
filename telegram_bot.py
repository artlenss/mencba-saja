import telebot
import sqlite3
import os
from datetime import datetime
from dotenv import load_dotenv
import threading
import time

# Load environment variables
load_dotenv()

# Ganti dengan token bot Anda
TOKEN = os.getenv('BOT_TOKEN', 'YOUR_BOT_TOKEN')

# Inisialisasi bot
bot = telebot.TeleBot(TOKEN)

# Fungsi untuk keep-alive di Railway
def keep_alive():
    """Fungsi untuk menjaga agar bot tetap running di Railway"""
    while True:
        time.sleep(300)  # Tunggu 5 menit

def init_db():
    """Inisialisasi database SQLite"""
    conn = sqlite3.connect('accounts.db')
    c = conn.cursor()
    
    # Buat tabel accounts jika belum ada
    c.execute('''CREATE TABLE IF NOT EXISTS accounts
                 (email TEXT PRIMARY KEY, password TEXT, notes TEXT, sold INTEGER DEFAULT 0)''')
    
    # Buat tabel sales jika belum ada
    c.execute('''CREATE TABLE IF NOT EXISTS sales
                 (email TEXT, telegram_user_id TEXT, telegram_username TEXT, 
                  date TEXT, FOREIGN KEY(email) REFERENCES accounts(email))''')
    
    conn.commit()
    conn.close()

def add_account(email, password, notes=""):
    """Tambah akun baru ke database"""
    conn = sqlite3.connect('accounts.db')
    c = conn.cursor()
    try:
        c.execute('INSERT INTO accounts (email, password, notes) VALUES (?, ?, ?)',
                 (email, password, notes))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def get_available_account():
    """Ambil akun yang belum terjual"""
    conn = sqlite3.connect('accounts.db')
    c = conn.cursor()
    c.execute('SELECT email, password, notes FROM accounts WHERE sold = 0 LIMIT 1')
    account = c.fetchone()
    conn.close()
    return account

def mark_as_sold(email, user_id, username):
    """Tandai akun sebagai terjual"""
    conn = sqlite3.connect('accounts.db')
    c = conn.cursor()
    
    # Update status akun
    c.execute('UPDATE accounts SET sold = 1 WHERE email = ?', (email,))
    
    # Simpan data penjualan
    c.execute('INSERT INTO sales (email, telegram_user_id, telegram_username, date) VALUES (?, ?, ?, ?)',
             (email, user_id, username, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    
    conn.commit()
    conn.close()

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, 
                "Selamat datang di Bot Penjual Akun Blackbox.ai!\n"
                "Gunakan /buy untuk membeli akun\n"
                "Gunakan /check untuk mengecek stok akun")

@bot.message_handler(commands=['check'])
def check_stock(message):
    conn = sqlite3.connect('accounts.db')
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM accounts WHERE sold = 0')
    count = c.fetchone()[0]
    conn.close()
    bot.reply_to(message, f"Stok akun tersedia: {count}")

@bot.message_handler(commands=['buy'])
def buy_account(message):
    account = get_available_account()
    if not account:
        bot.reply_to(message, "Maaf, stok akun sedang kosong!")
        return
    
    email, password, notes = account
    
    # Tandai akun sebagai terjual
    mark_as_sold(email, message.chat.id, message.from_user.username)
    
    # Kirim detail akun ke pembeli
    response = f"Pembelian berhasil!\n\nEmail: {email}\nPassword: {password}"
    if notes:
        response += f"\nCatatan: {notes}"
    response += "\n\nAkun ini sudah dihapus dari database dan tidak akan dijual ke orang lain."
    
    bot.reply_to(message, response)

@bot.message_handler(commands=['admin'])
def admin_command(message):
    # Ganti dengan ID Telegram Anda
    if str(message.chat.id) != os.getenv('ADMIN_ID', 'YOUR_TELEGRAM_ID'):
        bot.reply_to(message, "Anda tidak memiliki akses ke perintah ini!")
        return
        
    bot.reply_to(message, 
                "Admin Panel:\n"
                "/addaccount - Tambah akun baru\n"
                "/sales - Lihat riwayat penjualan")

@bot.message_handler(commands=['addaccount'])
def add_account_command(message):
    # Cek apakah user adalah admin
    if str(message.chat.id) != os.getenv('ADMIN_ID', 'YOUR_TELEGRAM_ID'):
        bot.reply_to(message, "Anda tidak memiliki akses ke perintah ini!")
        return
    
    # Format: /addaccount email password catatan(opsional)
    parts = message.text.split()
    if len(parts) < 3:
        bot.reply_to(message, "Format: /addaccount email password catatan(opsional)")
        return
        
    email = parts[1]
    password = parts[2]
    notes = ' '.join(parts[3:]) if len(parts) > 3 else ""
    
    if add_account(email, password, notes):
        bot.reply_to(message, f"Akun berhasil ditambahkan:\nEmail: {email}")
    else:
        bot.reply_to(message, f"Email {email} sudah ada di database!")

@bot.message_handler(commands=['sales'])
def sales_command(message):
    # Cek apakah user adalah admin
    if str(message.chat.id) != os.getenv('ADMIN_ID', 'YOUR_TELEGRAM_ID'):
        bot.reply_to(message, "Anda tidak memiliki akses ke perintah ini!")
        return
        
    conn = sqlite3.connect('accounts.db')
    c = conn.cursor()
    c.execute('''SELECT s.email, s.telegram_username, s.date 
                 FROM sales s 
                 ORDER BY s.date DESC LIMIT 10''')
    sales = c.fetchall()
    conn.close()
    
    if not sales:
        bot.reply_to(message, "Belum ada penjualan!")
        return
        
    response = "10 Penjualan Terakhir:\n\n"
    for email, username, date in sales:
        response += f"Email: {email}\n"
        response += f"Pembeli: @{username}\n"
        response += f"Tanggal: {date}\n\n"
    
    bot.reply_to(message, response)

def main():
    print("Bot Telegram sedang berjalan...")
    # Inisialisasi database
    init_db()
    
    # Jalankan thread keep-alive untuk Railway
    keep_alive_thread = threading.Thread(target=keep_alive)
    keep_alive_thread.daemon = True
    keep_alive_thread.start()
    
    # Jalankan bot
    while True:
        try:
            print("Bot dimulai...")
            bot.polling(none_stop=True)
        except Exception as e:
            print(f"Error: {str(e)}")
            time.sleep(15)

if __name__ == "__main__":
    main()
