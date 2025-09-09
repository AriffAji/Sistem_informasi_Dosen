from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory, send_file, jsonify
from flask_session import Session
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from redis import Redis
import sqlite3
from datetime import datetime, timedelta
import os
import calendar
import pandas as pd
import io
import logging   # <--- ini baris import logging
import traceback
from flask import send_file
from pywebpush import webpush, WebPushException

# setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

app = Flask(__name__)   # inisialisasi app Flask
app.logger.info("Aplikasi Flask sudah start 🚀")   # logging pertama kali

# --- Upload folder (buat default & set ke config) ---Z
UPLOAD_FOLDER = os.path.join(os.getcwd(), "uploads")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
# Pastikan ukuran maksimal upload (opsional): misal 16 MB
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024


# --- SECRET KEY ---
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    # Kalau di production tapi SECRET_KEY kosong → langsung error
    if os.getenv("RAILWAY_STATIC_URL") or os.getenv("FLASK_ENV") == "production":
        raise RuntimeError("SECRET_KEY tidak ditemukan di environment. Set di Railway > Variables.")
    # Fallback hanya untuk development lokal
    SECRET_KEY = "dev-secret-key"

app.secret_key = SECRET_KEY

# --- Konfigurasi Session ---
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = os.getenv("SESSION_TYPE", "filesystem")

# Cookie Hardening
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = bool(
    os.getenv("RAILWAY_STATIC_URL") or os.getenv("FLASK_ENV") == "production"
)

# Redis (jika SESSION_TYPE=redis)
if app.config["SESSION_TYPE"] == "redis":
    app.config["SESSION_REDIS"] = Redis.from_url(os.getenv("SESSION_REDIS"))

Session(app)

# --- Konfigurasi Path Database ---
DATABASE = os.getenv("DATABASE", "database.db")

# --- Fungsi Bantuan ---
def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

# --- Rute Utama dan Login ---
@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None

    if 'user_id' in session:
        return redirect(url_for('login_blocked'))

    # Kalau user submit form login
    if request.method == 'POST':
        nip = request.form['nip']
        password = request.form['password']

        conn = get_db_connection()
        user = conn.execute(
            'SELECT * FROM users WHERE nip = ? AND password = ?',
            (nip, password)
        ).fetchone()
        conn.close()

        if user:
            # Simpan data ke session
            session['user_id'] = user['nip']
            session['user_name'] = user['nama_lengkap']
            session['user_role'] = user['role']
            session['user_jurusan'] = user['jurusan']

            # Daftar role staf yang hanya melihat dashboard absensi pribadi
            ROLES_STAF_SAJA = ['Dosen', 'P3M', 'UP3M', 'TIK', 'PP']

            # Redirect sesuai role
            if user['role'] == 'Dosen':
                return redirect(url_for('dashboard_dosen'))
            elif user['role'] == 'Sekjur':
                return redirect(url_for('dashboard_sekjur'))
            elif user['role'] == 'Kajur':
                return redirect(url_for('dashboard_kajur'))
            elif user['role'] == 'Wadir1':
                return redirect(url_for('dashboard_wadir1'))
            elif user['role'] == 'Wadir2':
                return redirect(url_for('dashboard_wadir2'))
            elif user['role'] == 'Wadir3':
                return redirect(url_for('dashboard_wadir3'))
            elif user['role'] == 'Kajur':
                return redirect(url_for('dashboard_kajur'))
            elif user['role'] == 'Admin':
                return redirect(url_for('dashboard_admin'))
            else:
                error = 'Role Anda tidak dikenali atau tidak memiliki halaman dashboard.'
                return render_template('login.html', error=error)
        else:
            # Password / NIP salah
            error = 'NIP atau Password salah.'
            # redirect ke /login GET + param error
            return redirect(url_for('login', error='1'))

    # Kalau GET request → tampilkan form login
    error_message = None
    if request.args.get('error') == '1':
        error_message = 'NIP atau Password salah.'
    return render_template('login.html', error=error_message)


# --- Rute jika user back ke halaman login ---
@app.route('/login-blocked')
def login_blocked():
    # pastikan user sudah login
    if 'user_role' not in session:
        return redirect(url_for('login'))

    # mapping role ke dashboard
    role_redirect_map = {
        "Dosen": url_for('dashboard_dosen'),
        "Kajur": url_for('dashboard_kajur'),
        "Sekjur": url_for('dashboard_sekjur'),
        "Wadir1": url_for('dashboard_wadir1'),
        "Wadir2": url_for('dashboard_wadir2'),
        "Wadir3": url_for('dashboard_wadir3'),
        "Direktur": url_for('dashboard_direktur'),
        "Admin": url_for('dashboard_admin'),
    }

    role = session['user_role']
    dashboard_url = role_redirect_map.get(role, url_for('login'))

    return render_template('login_blocked.html', dashboard_url=dashboard_url)

# Handle Back Session 
@app.after_request
def add_no_cache_headers(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

# --- Rute Dosen ---
@app.route('/dashboard_dosen')
def dashboard_dosen():
    ROLES_STAF = [
        'Dosen', 'Sekjur', 'P3M', 'UP3M', 'TIK', 'PP',
        'Wadir1', 'Wadir2', 'Wadir3', 'Kajur', 'Direktur'
    ]
    if 'user_role' not in session or session['user_role'] not in ROLES_STAF:
        return redirect(url_for('login'))

    conn = get_db_connection()
    user_nip = session['user_id']

    records_raw = conn.execute('SELECT *, rowid as id FROM attendance WHERE nip = ? ORDER BY tanggal DESC', (user_nip,)).fetchall()
    user_data = conn.execute("SELECT jatah_cuti_tahunan FROM users WHERE nip = ?", (user_nip,)).fetchone()
    
    current_year = str(datetime.now().year)
    # --- PERBAIKAN: Query diubah menjadi spesifik hanya untuk 'Cuti Tahunan' ---
    total_cuti_terpakai_data = conn.execute(
        """
        SELECT COUNT(*) as total FROM attendance 
        WHERE nip = ? AND status LIKE 'Disetujui%' AND keterangan LIKE '%Cuti Tahunan%' AND strftime('%Y', tanggal) = ?
        """,
        (user_nip, current_year)
    ).fetchone()

    current_month = datetime.now().strftime('%Y-%m')
    lupa_masuk_data = conn.execute("SELECT COUNT(*) as total FROM clarifications WHERE nip_pengaju = ? AND jenis_surat = 'Lupa Absen Masuk' AND strftime('%Y-%m', tanggal_pengajuan) = ?", (user_nip, current_month)).fetchone()
    lupa_pulang_data = conn.execute("SELECT COUNT(*) as total FROM clarifications WHERE nip_pengaju = ? AND jenis_surat = 'Lupa Absen Pulang' AND strftime('%Y-%m', tanggal_pengajuan) = ?", (user_nip, current_month)).fetchone()
    
    lupa_masuk_count = lupa_masuk_data['total'] if lupa_masuk_data else 0
    lupa_pulang_count = lupa_pulang_data['total'] if lupa_pulang_data else 0

    conn.close() 

    jatah_cuti_tahunan = user_data['jatah_cuti_tahunan'] if user_data and user_data['jatah_cuti_tahunan'] is not None else 0
    total_cuti_terpakai = total_cuti_terpakai_data['total'] if total_cuti_terpakai_data else 0
    sisa_cuti_tahunan = jatah_cuti_tahunan - total_cuti_terpakai
    
    processed_records = []
    # --- BLOK LENGKAP ANDA DIMASUKKAN KEMBALI ---
    time_fmt = '%H:%M:%S.%f'
    for record in records_raw:
        rec = dict(record)
        rec['tanggal_formatted'] = datetime.strptime(rec['tanggal'], '%Y-%m-%d %H:%M:%S').strftime('%d/%m/%Y')
        jam_masuk, jam_pulang = rec.get('jam masuk'), rec.get('jam pulang')
        status, keterangan = rec.get('status'), rec.get('keterangan')
        
        rec['jam_masuk_formatted'] = datetime.strptime(jam_masuk, time_fmt).strftime('%H:%M') if jam_masuk else " - "
        rec['jam_pulang_formatted'] = datetime.strptime(jam_pulang, time_fmt).strftime('%H:%M') if jam_pulang else " - "
        
        if status and "Menunggu" in status:
            rec.update({'status_text': 'Menunggu Persetujuan', 'status_color': 'yellow', 'checkbox_enabled': False})
        elif status and "Disetujui" in status:
            if keterangan:
                rec.update({'status_text': f"Disetujui - {keterangan}", 'status_color': 'green', 'checkbox_enabled': False})
            else:
                rec.update({'status_text': status, 'status_color': 'green', 'checkbox_enabled': False})
        elif status and "Ditolak" in status:
            rec.update({'status_text': keterangan, 'status_color': 'red', 'checkbox_enabled': True})
        elif jam_masuk and jam_pulang:
            dur = datetime.strptime(jam_pulang, time_fmt) - datetime.strptime(jam_masuk, time_fmt)
            if dur.total_seconds() >= 4 * 3600:
                rec.update({'status_text': 'Kehadiran Terpenuhi', 'status_color': 'green', 'checkbox_enabled': False})
            else:
                rec.update({'status_text': 'Kurang Dari 4 Jam', 'status_color': 'red', 'checkbox_enabled': False})
        else:
            rec.update({'status_text': 'Perlu Klarifikasi', 'status_color': 'red', 'checkbox_enabled': True})
        processed_records.append(rec)
    
    summary_message = ""
    summary_color = ""
    if not processed_records:
        summary_message = "Belum ada data riwayat absensi untuk ditampilkan."
        summary_color = "grey"
    else:
        ada_klarifikasi = any(rec['status_color'] == 'red' for rec in processed_records)
        if ada_klarifikasi:
            summary_message = "Anda Memiliki Tanggal yang Perlu di Klarifikasi"
            summary_color = "red"
        else:
            summary_message = "Selamat! Semua Kehadiran Anda Terpenuhi"
            summary_color = "green"

    return render_template(
        'dashboard_dosen.html',
        records=processed_records,
        records_json=processed_records,
        jatah_cuti=jatah_cuti_tahunan,
        cuti_terpakai=total_cuti_terpakai,
        sisa_cuti=sisa_cuti_tahunan,
        lupa_masuk_count=lupa_masuk_count,
        lupa_pulang_count=lupa_pulang_count,
        summary_message=summary_message,
        summary_color=summary_color
    )

@app.route('/submit_klarifikasi', methods=['POST'])
def submit_klarifikasi():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    user_nip = session['user_id']
    
    # Mencari atasan dari pengguna yang mengajukan
    user_data = conn.execute("SELECT id_atasan FROM users WHERE nip = ?", (user_nip,)).fetchone()
    
    if not user_data or not user_data['id_atasan']:
        flash('Proses Gagal: Atasan Anda tidak terdaftar di sistem.', 'danger')
        conn.close()
        return redirect(request.referrer)

    id_atasan = user_data['id_atasan']

    record_ids = request.form.getlist('record_ids')
    
    # Validasi duplikat
    for record_id in record_ids:
        attendance_record = conn.execute("SELECT status FROM attendance WHERE rowid = ?", (record_id,)).fetchone()
        if not attendance_record or (attendance_record['status'] and "Menunggu Persetujuan" in attendance_record['status']):
            conn.close()
            flash("GAGAL: Salah satu tanggal yang Anda pilih sudah pernah diajukan dan sedang menunggu persetujuan.", "error")
            return redirect(url_for('dashboard_dosen'))

    # Jika semua validasi lolos, baru lanjutkan proses penyimpanan
    kategori_surat = request.form.get('kategori_surat')
    jenis_surat = request.form.get('jenis_surat')

    # Logika untuk menangani file upload
    file_path = None
    if 'file_bukti' in request.files:
        file = request.files['file_bukti']
        if file and file.filename != '':
            filename = secure_filename(f"bukti-{user_nip}-{datetime.now().strftime('%Y%m%d%H%M%S')}-{file.filename}")
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)

    # Memproses setiap tanggal yang dipilih
    for record_id in record_ids:
        attendance_record = conn.execute("SELECT * FROM attendance WHERE rowid = ?", (record_id,)).fetchone()
        if attendance_record:
            conn.execute(
                """
                INSERT INTO clarifications (
                    nip_pengaju, nama_lengkap, jurusan, tanggal_klarifikasi, 
                    kategori_surat, jenis_surat, nip_approver_sekarang, status_final,
                    file_bukti
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_nip, 
                    session['user_name'], 
                    session['user_jurusan'], 
                    attendance_record['tanggal'], 
                    kategori_surat,
                    jenis_surat, 
                    id_atasan,
                    'Diajukan',
                    file_path
                )
            )
            # Update status di tabel attendance
            conn.execute("UPDATE attendance SET status = 'Menunggu Persetujuan' WHERE rowid = ?", (record_id,))

    conn.commit()

    # ==========================================================
    # ==          PANGGIL FUNGSI NOTIFIKASI DI SINI           ==
    # ==========================================================
    try:
        nama_pengaju = session.get('user_name', 'Seorang Dosen')
        print(f"Mengirim notifikasi pengajuan baru ke atasan NIP: {id_atasan}")
        send_push_notification(
            target_nip=id_atasan,
            title="Pengajuan Klarifikasi Baru",
            body=f"Ada pengajuan baru dari {nama_pengaju}. Mohon segera ditinjau.",
            url="/dashboard_kajur" # Sesuaikan URL dashboard atasan jika berbeda
        )
    except Exception as e:
        print(f"GAGAL MENGIRIM NOTIFIKASI (submit_klarifikasi): {e}")
    # ==========================================================
    
    conn.close()

    flash('Klarifikasi berhasil diajukan.', 'success')
    return redirect(url_for('dashboard_dosen'))

@app.route('/dashboard_sekjur')
def dashboard_sekjur():
    # Pengecekan role
    if 'user_role' not in session or session['user_role'] != 'Sekjur':
        return redirect(url_for('login'))

    conn = get_db_connection()
    sekjur_nip = session['user_id']
    sekjur_jurusan = session['user_jurusan']
    
    # Cari tahu siapa atasan dari Sekjur ini (yaitu NIP Kajur)
    atasan_data = conn.execute("SELECT id_atasan FROM users WHERE nip = ?", (sekjur_nip,)).fetchone()
    
    # Inisialisasi daftar tugas sebagai list kosong
    pending_approvals = []
    
    # HANYA jalankan query jika atasan ditemukan untuk mencegah error
    if atasan_data and atasan_data['id_atasan']:
        kajur_nip = atasan_data['id_atasan']
        
        # Ambil tugas approval: yang ditujukan untuk Kajur DAN yang mungkin ditujukan untuk Sekjur
        pending_approvals = conn.execute(
            """
            SELECT * FROM clarifications 
            WHERE (nip_approver_sekarang = ? OR nip_approver_sekarang = ?) 
            AND jurusan = ?
            """,
            (kajur_nip, sekjur_nip, sekjur_jurusan)
        ).fetchall()

    # Ambil daftar dosen & sekjur di jurusan yang sama
    bawahan_list = conn.execute(
        "SELECT * FROM users WHERE jurusan = ? AND role IN ('Dosen', 'Sekjur') ORDER BY nama_lengkap",
        (sekjur_jurusan,)
    ).fetchall()

    conn.close()
    
    # Render template baru: dashboard_sekjur.html
    return render_template('dashboard_sekjur.html', records=pending_approvals, dosen_list=bawahan_list)

# --- Rute Kajur ---
@app.route('/dashboard_kajur')
def dashboard_kajur():
    if 'user_role' not in session or session['user_role'] != 'Kajur':
        return redirect(url_for('login'))

    conn = get_db_connection()
    user_nip = session['user_id'] # NIP dari Kajur yang sedang login

    # LOGIKA BARU: Ambil tugas berdasarkan NIP approver, bukan status
    pending_approvals = conn.execute(
        "SELECT * FROM clarifications WHERE nip_approver_sekarang = ?",
        (user_nip,)
    ).fetchall()

    # LOGIKA BARU: Ambil bawahan berdasarkan id_atasan, bukan jurusan
    bawahan_list = conn.execute(
        "SELECT * FROM users WHERE id_atasan = ? ORDER BY nama_lengkap",
        (user_nip,)
    ).fetchall()

    conn.close()
    
    # Ganti 'dosen_list' menjadi 'bawahan_list' saat mengirim ke template
    return render_template('dashboard_kajur.html', records=pending_approvals, dosen_list=bawahan_list)

@app.route('/proses_klarifikasi', methods=['POST'])
def proses_klarifikasi():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    clarification_id = request.form.get('clarification_id')
    action = request.form.get('action')
    approver_role = session.get('user_role', 'Atasan')

    conn = get_db_connection()
    
    klarifikasi = conn.execute("SELECT * FROM clarifications WHERE id = ?", (clarification_id,)).fetchone()
    
    if not klarifikasi:
        flash("Klarifikasi tidak ditemukan.", "danger")
        conn.close()
        return redirect(request.referrer)

    nip_pengaju = klarifikasi['nip_pengaju']
    tanggal_klarifikasi_obj = datetime.strptime(klarifikasi['tanggal_klarifikasi'], '%Y-%m-%d %H:%M:%S')
    
    # Tentukan title dan body notifikasi berdasarkan aksi
    tanggal_str = tanggal_klarifikasi_obj.strftime('%d %B %Y')
    notif_title = ""
    notif_body = ""
    
    if action == 'setuju':
        kategori = klarifikasi['kategori_surat']
        singkatan = "FL" if kategori == "Fleksibel" else "NF"
        
        status_final_clarification = f'Disetujui oleh {approver_role}'
        status_final_attendance = f'Disetujui - Surat {singkatan}'
        keterangan_attendance = klarifikasi['jenis_surat']

        conn.execute(
            "UPDATE clarifications SET status_final = ?, nip_approver_sekarang = NULL WHERE id = ?",
            (status_final_clarification, clarification_id)
        )
        conn.execute(
            "UPDATE attendance SET status = ?, keterangan = ? WHERE nip = ? AND date(tanggal) = date(?)",
            (status_final_attendance, keterangan_attendance, nip_pengaju, tanggal_klarifikasi_obj)
        )
        
        # Siapkan pesan notifikasi untuk persetujuan
        notif_title = "Pengajuan Klarifikasi Disetujui"
        notif_body = f"Pengajuan Anda untuk tanggal {tanggal_str} telah disetujui."
        
    elif action == 'tolak':
        alasan = request.form.get('alasan_penolakan', 'Tidak ada alasan spesifik')
        
        status_final_clarification = f'Ditolak oleh {approver_role}'
        status_final_attendance = 'Ditolak'
        keterangan_attendance = f"{alasan} - Silahkan Klarifikasi Ulang"
        
        conn.execute(
            "UPDATE clarifications SET status_final = ?, catatan_revisi = ?, nip_approver_sekarang = NULL WHERE id = ?",
            (status_final_clarification, alasan, clarification_id)
        )
        conn.execute(
            "UPDATE attendance SET status = ?, keterangan = ? WHERE nip = ? AND date(tanggal) = date(?)",
            (status_final_attendance, keterangan_attendance, nip_pengaju, tanggal_klarifikasi_obj)
        )
        
        # Siapkan pesan notifikasi untuk penolakan
        notif_title = "Pengajuan Klarifikasi Ditolak"
        notif_body = f"Pengajuan Anda untuk tanggal {tanggal_str} ditolak. Silakan cek dashboard Anda."
        
    conn.commit()

    # ==========================================================
    # ==          PANGGIL FUNGSI NOTIFIKASI DI SINI           ==
    # ==========================================================
    try:
        print(f"Mengirim notifikasi status ke dosen NIP: {nip_pengaju}")
        send_push_notification(
            target_nip=nip_pengaju,
            title=notif_title,
            body=notif_body,
            url="/dashboard_dosen" # Arahkan dosen ke dashboard pribadinya
        )
    except Exception as e:
        print(f"GAGAL MENGIRIM NOTIFIKASI (proses_klarifikasi): {e}")
    # ==========================================================

    conn.close()

    flash(f"Pengajuan telah berhasil di-{action}.", 'success')
    return redirect(request.referrer)

# --- Rute Admin ---
@app.route('/dashboard_admin')
def dashboard_admin():
    if 'user_role' not in session or session['user_role'] != 'Admin':
        return redirect(url_for('login'))
    conn = get_db_connection()
    all_users = conn.execute("SELECT * FROM users ORDER BY role, nama_lengkap").fetchall()
    all_history = conn.execute("SELECT * FROM clarifications ORDER BY tanggal_pengajuan DESC").fetchall()
    conn.close()
    return render_template('dashboard_admin.html', users=all_users, histories=all_history)

# Pastikan 'flash' sudah ada di baris import Anda di bagian atas file
# Contoh: from flask import Flask, render_template, request, redirect, url_for, session, flash

# --- Rute Tambah Pengguna ---
@app.route('/tambah_pengguna', methods=['GET', 'POST'])
def tambah_pengguna():
    # Memeriksa apakah pengguna adalah Admin
    if 'user_role' not in session or session['user_role'] != 'Admin':
        return redirect(url_for('login'))
    
    conn = get_db_connection()

    # Logika saat form dikirim (method POST)
    if request.method == 'POST':
        # Mengambil semua data dari formulir, termasuk kolom-kolom baru
        nip = request.form['nip']
        password = request.form['password']
        nama_lengkap = request.form['nama_lengkap']
        jurusan = request.form['jurusan']
        detail_jurusan = request.form['detail_jurusan']
        role = request.form['role']
        id_atasan = request.form.get('id_atasan') # Menggunakan .get() agar aman jika tidak diisi
        jatah_cuti = request.form.get('jatah_cuti', 12) # Memberi nilai default 12 jika tidak diisi

        # Perintah INSERT ke database diperbarui dengan kolom-kolom baru
        conn.execute("""
            INSERT INTO users (nip, password, nama_lengkap, jurusan, "detail jurusan", role, id_atasan, jatah_cuti_tahunan)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (nip, password, nama_lengkap, jurusan, detail_jurusan, role, id_atasan, jatah_cuti))
        
        conn.commit()
        conn.close()
        flash('Pengguna baru berhasil ditambahkan.', 'success')
        return redirect(url_for('dashboard_admin'))

    # Logika saat halaman pertama kali dibuka (method GET)
    # Mengambil daftar pengguna yang bisa menjadi atasan untuk mengisi dropdown
    potential_superiors = conn.execute("SELECT nip, nama_lengkap, role FROM users WHERE role IN ('Kajur', 'Wadir1', 'Wadir2', 'Wadir3', 'Direktur') ORDER BY nama_lengkap").fetchall()
    conn.close()
    
    # Mengirim daftar atasan tersebut ke template HTML
    return render_template('tambah_pengguna.html', superiors=potential_superiors)

# --- Rute Wadir 1 ---
@app.route('/dashboard_wadir1')
def dashboard_wadir1():
    if 'user_role' not in session or session['user_role'] != 'Wadir1':
        return redirect(url_for('login'))

    conn = get_db_connection()
    user_nip = session['user_id']

    # Logikanya sama persis dengan Kajur
    pending_approvals = conn.execute(
        "SELECT * FROM clarifications WHERE nip_approver_sekarang = ?",
        (user_nip,)
    ).fetchall()

    bawahan_list = conn.execute(
        "SELECT * FROM users WHERE id_atasan = ? ORDER BY nama_lengkap",
        (user_nip,)
    ).fetchall()

    conn.close()
    
    # Kirim ke template yang sesuai
    return render_template('dashboard_wadir1.html', records=pending_approvals, bawahan_list=bawahan_list)

# --- Rute Wadir 2 ---
@app.route('/dashboard_wadir2')
def dashboard_wadir2():
    if 'user_role' not in session or session['user_role'] != 'Wadir2':
        return redirect(url_for('login'))

    conn = get_db_connection()
    user_nip = session['user_id']

    pending_approvals = conn.execute(
        "SELECT * FROM clarifications WHERE nip_approver_sekarang = ?",
        (user_nip,)
    ).fetchall()

    bawahan_list = conn.execute(
        "SELECT * FROM users WHERE id_atasan = ? ORDER BY nama_lengkap",
        (user_nip,)
    ).fetchall()

    conn.close()
    
    return render_template('dashboard_wadir2.html', records=pending_approvals, bawahan_list=bawahan_list)

# --- Rute Wadir 3 ---
@app.route('/dashboard_wadir3')
def dashboard_wadir3():
    if 'user_role' not in session or session['user_role'] != 'Wadir3':
        return redirect(url_for('login'))

    conn = get_db_connection()
    user_nip = session['user_id']

    pending_approvals = conn.execute(
        "SELECT * FROM clarifications WHERE nip_approver_sekarang = ?",
        (user_nip,)
    ).fetchall()

    bawahan_list = conn.execute(
        "SELECT * FROM users WHERE id_atasan = ? ORDER BY nama_lengkap",
        (user_nip,)
    ).fetchall()

    conn.close()
    
    return render_template('dashboard_wadir3.html', records=pending_approvals, bawahan_list=bawahan_list)

# --- Rute Direktur ---
@app.route('/dashboard_direktur')
def dashboard_direktur():
    if 'user_role' not in session or session['user_role'] != 'Direktur':
        return redirect(url_for('login'))

    conn = get_db_connection()
    user_nip = session['user_id']

    pending_approvals = conn.execute(
        "SELECT * FROM clarifications WHERE nip_approver_sekarang = ?",
        (user_nip,)
    ).fetchall()

    bawahan_list = conn.execute(
        "SELECT * FROM users WHERE id_atasan = ? ORDER BY nama_lengkap",
        (user_nip,)
    ).fetchall()

    conn.close()
    
    return render_template('dashboard_direktur.html', records=pending_approvals, bawahan_list=bawahan_list)

# --- Rute Tambah Cuti ---
@app.route('/input_cuti', methods=['GET', 'POST'])
def input_cuti():
    if 'user_role' not in session or session['user_role'] != 'Admin':
        return redirect(url_for('login'))

    conn = get_db_connection()

    if request.method == 'POST':
        nip = request.form['nip']
        nama_lengkap = request.form['nama_lengkap']
        tanggal_surat = request.form['tanggal_surat']
        start_date_str = request.form['start_date']
        end_date_str = request.form['end_date']
        jenis_cuti = request.form['jenis_cuti']
        alasan_cuti = request.form.get('alasan_cuti', '')

        user_info = conn.execute("SELECT * FROM users WHERE nip = ?", (nip,)).fetchone()
        if not user_info:
            conn.close()
            flash(f"GAGAL: NIP '{nip}' tidak ditemukan di database.", "error")
            return redirect(url_for('input_cuti'))

        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        
        dates_to_update = []
        current_date_check = start_date
        while current_date_check <= end_date:
            if current_date_check.weekday() < 5:
                date_str_check = current_date_check.strftime('%Y-%m-%d')
                
                record = conn.execute("SELECT rowid, status, \"jam masuk\", \"jam pulang\" FROM attendance WHERE nip = ? AND date(tanggal) = ?", (nip, date_str_check)).fetchone()
                
                if not record:
                    full_date_str = date_str_check + " 00:00:00"
                    cursor = conn.cursor()
                    cursor.execute("INSERT INTO attendance (nip, tanggal) VALUES (?, ?)", (nip, full_date_str))
                    conn.commit()
                    record_id = cursor.lastrowid
                    # Buat dictionary tiruan agar sisa kode berjalan
                    record = {'rowid': record_id, 'status': None, 'jam masuk': None, 'jam pulang': None}

                is_jam_masuk_filled = record['jam masuk'] is not None
                is_jam_pulang_filled = record['jam pulang'] is not None
                current_status = record['status'] if record['status'] else ""
                INVALID_STATUSES = ['Disetujui', 'Kehadiran Terpenuhi', 'Menunggu Persetujuan']
                is_status_final = any(invalid_status in current_status for invalid_status in INVALID_STATUSES)

                if is_jam_masuk_filled or is_jam_pulang_filled or is_status_final:
                    conn.close()
                    flash(f"GAGAL: Input cuti untuk tanggal {date_str_check} tidak diizinkan karena sudah ada aktivitas.", "error")
                    return redirect(url_for('input_cuti'))
                
                dates_to_update.append(record['rowid'])
            current_date_check += timedelta(days=1)
        
        requested_workdays = len(dates_to_update)
        # --- PERBAIKAN: Validasi sisa cuti HANYA untuk 'Cuti Tahunan' ---
        if jenis_cuti == 'Cuti Tahunan':
            jatah_cuti_tahunan = user_info['jatah_cuti_tahunan']
            current_year = str(datetime.now().year)
            total_cuti_terpakai_data = conn.execute(
                "SELECT COUNT(*) as total FROM attendance WHERE nip = ? AND status LIKE 'Disetujui%' AND keterangan LIKE '%Cuti Tahunan%' AND strftime('%Y', tanggal) = ?",
                (nip, current_year)
            ).fetchone()
            total_cuti_terpakai = total_cuti_terpakai_data['total']
            sisa_cuti = jatah_cuti_tahunan - total_cuti_terpakai
            if requested_workdays > sisa_cuti:
                conn.close()
                flash(f"GAGAL: Jatah cuti tidak cukup. Sisa {sisa_cuti}, diminta {requested_workdays}.", "error")
                return redirect(url_for('input_cuti'))

        file_path = None
        if 'file_surat_cuti' in request.files:
            file = request.files['file_surat_cuti']
            if file.filename != '':
                filename = secure_filename(f"cuti-{nip}-{start_date_str}-{file.filename}")
                file_path = os.path.join(app.config.get('UPLOAD_FOLDER', 'uploads'), filename)
                file.save(file_path)
        
        conn.execute("""
            INSERT INTO cuti_dosen (nip, nama_lengkap, tanggal_surat, tanggal_mulai, tanggal_selesai, 
                                     jenis_cuti, alasan_cuti, file_surat_cuti, diinput_oleh)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (nip, nama_lengkap, tanggal_surat, start_date_str, end_date_str, jenis_cuti, 
              alasan_cuti, file_path, session.get('user_name')))
        
        keterangan_lengkap = f"{jenis_cuti} - {alasan_cuti}" if alasan_cuti else jenis_cuti
        
        for row_id in dates_to_update:
            conn.execute("UPDATE attendance SET status = 'Disetujui (Input Admin)', keterangan = ? WHERE rowid = ?", (keterangan_lengkap, row_id))
        
        conn.commit()
        conn.close()
        flash(f"Cuti berhasil diinput untuk {nama_lengkap} selama {requested_workdays} hari kerja.", "success")
        return redirect(url_for('input_cuti'))

    # Bagian GET (menampilkan halaman)
    staff_rows = conn.execute("SELECT nip, nama_lengkap FROM users WHERE role != 'Admin' ORDER BY nama_lengkap").fetchall()
    list_staff = [dict(row) for row in staff_rows]
    history_cuti = conn.execute("SELECT * FROM cuti_dosen ORDER BY tanggal_input DESC").fetchall()
    conn.close()
    
    return render_template('input_cuti.html', list_staff=list_staff, histories=history_cuti)

# --- Rute Absensi ---
@app.route('/get_absensi_summary/<nip>')
def get_absensi_summary(nip):
    # Daftar semua role yang boleh menggunakan fitur ini (dari kode Anda)
    ROLES_APPROVAL = [
        'Admin', 'Kajur', 'Sekjur', 
        'Wadir1', 'Wadir2', 'Wadir3', 'Direktur'
    ]
    if 'user_role' not in session or session['user_role'] not in ROLES_APPROVAL:
        return jsonify({"error": "Unauthorized"}), 403

    conn = get_db_connection()
    
    target_user = conn.execute('SELECT * FROM users WHERE nip = ?', (nip,)).fetchone()
    if not target_user:
        conn.close()
        return jsonify({'error': 'User not found'}), 404
    
    # --- PERBAIKAN SATU-SATUNYA ADA DI SINI ---
    # Perhitungan Cuti Tahunan yang Akurat
    jatah_cuti_tahunan = target_user['jatah_cuti_tahunan'] if target_user and target_user['jatah_cuti_tahunan'] is not None else 0
    current_year = str(datetime.now().year)
    total_cuti_terpakai_data = conn.execute(
        """
        SELECT COUNT(*) as total FROM attendance 
        WHERE nip = ? AND status LIKE 'Disetujui%' AND keterangan LIKE '%Cuti Tahunan%' AND strftime('%Y', tanggal) = ?
        """,
        (nip, current_year)
    ).fetchone()
    total_cuti_terpakai = total_cuti_terpakai_data['total'] if total_cuti_terpakai_data else 0
    sisa_cuti_tahunan = jatah_cuti_tahunan - total_cuti_terpakai
    # --- AKHIR PERBAIKAN ---

    # Mengambil data absensi bulan terakhir (Logika Anda yang sudah benar)
    last_month_record = conn.execute(
        "SELECT strftime('%Y-%m', tanggal) as last_month FROM attendance WHERE nip = ? ORDER BY tanggal DESC LIMIT 1",
        (nip,)
    ).fetchone()

    processed_records = []
    if last_month_record:
        target_month = last_month_record['last_month']
        records_raw = conn.execute(
            "SELECT * FROM attendance WHERE nip = ? AND strftime('%Y-%m', tanggal) = ? ORDER BY tanggal DESC", 
            (nip, target_month)
        ).fetchall()

        time_fmt = '%H:%M:%S.%f'
        for record in records_raw:
            rec = dict(record)
            rec['tanggal_formatted'] = datetime.strptime(rec['tanggal'], '%Y-%m-%d %H:%M:%S').strftime('%d/%m/%Y')
            jam_masuk, jam_pulang = rec.get('jam masuk'), rec.get('jam pulang')
            status, keterangan = rec.get('status'), rec.get('keterangan') # Menggunakan .get() di sini aman
            rec['jam_masuk_formatted'] = datetime.strptime(jam_masuk, time_fmt).strftime('%H:%M') if jam_masuk else "-"
            rec['jam_pulang_formatted'] = datetime.strptime(jam_pulang, time_fmt).strftime('%H:%M') if jam_pulang else "-"

            # --- BLOK LOGIKA PEWARNAAN ANDA YANG SUDAH TERBUKTI BENAR ---
            if status and "Menunggu" in status:
                rec.update({'status_text': 'Menunggu Persetujuan', 'status_color': 'status-yellow'})
            elif status and "Disetujui" in status:
                if keterangan:
                    rec.update({'status_text': f"Disetujui - {keterangan}", 'status_color': 'status-green'})
                else:
                    rec.update({'status_text': status, 'status_color': 'status-green'})
            elif status and "Ditolak" in status:
                rec.update({'status_text': keterangan, 'status_color': 'status-red'})
            elif jam_masuk and jam_pulang:
                dur = datetime.strptime(jam_pulang, time_fmt) - datetime.strptime(jam_masuk, time_fmt)
                if dur.total_seconds() >= 4 * 3600:
                    rec.update({'status_text': 'Kehadiran Terpenuhi', 'status_color': 'status-green'})
                else:
                    rec.update({'status_text': 'Kurang Dari 4 Jam', 'status_color': 'status-red'})
            else:
                rec.update({'status_text': 'Perlu Klarifikasi', 'status_color': 'status-red'})
            
            processed_records.append(rec)
    
    conn.close()

    # Mengembalikan data dengan format yang benar
    return jsonify({
        "nama_lengkap": target_user['nama_lengkap'],
        "records": processed_records,
        "jatah_cuti": jatah_cuti_tahunan,
        "cuti_terpakai": total_cuti_terpakai,
        "sisa_cuti": sisa_cuti_tahunan
    })

# --- Rute Rekap Laporan ---
@app.route('/rekap_laporan_view')
def rekap_laporan_view():
    if 'user_role' not in session or session['user_role'] != 'Admin':
        return redirect(url_for('login'))

    try:
        conn = get_db_connection()

        # --- Bagian Pengambilan Data (Sudah Benar) ---
        target_month = '2025-07'
        year, month = map(int, target_month.split('-'))

        all_staff = conn.execute("SELECT nip, nama_lengkap, jurusan, \"detail jurusan\" FROM users WHERE role != 'Admin' ORDER BY jurusan, nama_lengkap").fetchall()
        attendance_data = conn.execute("SELECT * FROM attendance WHERE strftime('%Y-%m', tanggal) = ?", (target_month,)).fetchall()
        approved_clarifications = conn.execute(
            "SELECT nip_pengaju, tanggal_klarifikasi, kategori_surat FROM clarifications WHERE strftime('%Y-%m', tanggal_klarifikasi) = ? AND status_final LIKE 'Disetujui%'", 
            (target_month,)
        ).fetchall()
        
        conn.close()

        # --- Bagian Pemrosesan Data ---
        num_days = calendar.monthrange(year, month)[1]
        days_in_month = list(range(1, num_days + 1))
        selected_bulan_formatted = datetime(year, month, 1).strftime("%B %Y")

        report_data = {}
        for staff in all_staff:
            jurusan = staff['jurusan']
            detail_jurusan = staff['detail jurusan']
            if jurusan not in report_data:
                report_data[jurusan] = { 'nama_jurusan': detail_jurusan, 'staff_data': {} }
            report_data[jurusan]['staff_data'][staff['nip']] = {
                'nama': staff['nama_lengkap'],
                'absensi': {},
                'summary_counts': {'KT': 0, 'PK': 0, 'NF': 0, 'FL': 0, 'CT': 0, 'IZ': 0}
            }

        clarif_dict = {(item['nip_pengaju'], item['tanggal_klarifikasi'].split(' ')[0]): item['kategori_surat'] for item in approved_clarifications}

        # --- PERBAIKAN UTAMA ADA DI DALAM LOOP INI ---
        for record in attendance_data:
            nip = record['nip']
            
            current_unit_data = None
            for unit_data in report_data.values():
                if nip in unit_data['staff_data']:
                    current_unit_data = unit_data['staff_data'][nip]
                    break
            
            if not current_unit_data:
                continue

            try:
                # --- PERBAIKAN: Menggunakan akses dictionary `record['...']` ---
                tanggal_obj = datetime.strptime(record['tanggal'], '%Y-%m-%d %H:%M:%S')
                day = tanggal_obj.day
                tanggal_str = tanggal_obj.strftime('%Y-%m-%d')
                
                status = record['status'] if 'status' in record.keys() else ''
                jam_masuk = record['jam masuk'] if 'jam masuk' in record.keys() else None
                jam_pulang = record['jam pulang'] if 'jam pulang' in record.keys() else None
                keterangan = record['keterangan'] if 'keterangan' in record.keys() else ''

                kode = 'PK'

                if status and "Disetujui" in status:
                    if 'Cuti' in keterangan: kode = 'CT'
                    elif (nip, tanggal_str) in clarif_dict:
                        kategori = clarif_dict.get((nip, tanggal_str))
                        if kategori and 'Non Fleksibel' in kategori: kode = 'NF'
                        elif kategori and 'Fleksibel' in kategori: kode = 'FL'
                        else: kode = 'IZ'
                    else: kode = 'IZ'
                elif jam_masuk and jam_pulang:
                    dur = datetime.strptime(jam_pulang, '%H:%M:%S.%f') - datetime.strptime(jam_masuk, '%H:%M:%S.%f')
                    if dur.total_seconds() >= 4 * 3600:
                        kode = 'KT'
                
                current_unit_data['absensi'][day] = kode
                current_unit_data['summary_counts'][kode] += 1

            except Exception as e:
                # Logging yang lebih baik untuk debugging
                print(f"Melewatkan data error untuk NIP {nip} pada tanggal {record['tanggal']}: {e}")
                continue

        # --- Finalisasi Data (Tidak Ada Perubahan di Sini) ---
        report_data_per_jurusan = []
        for jurusan_key, data in report_data.items():
            staff_list = []
            for nip, staff_data in data['staff_data'].items():
                summary_counts = staff_data['summary_counts']
                summary_str = ", ".join([f"{k}:{v}" for k, v in summary_counts.items() if v > 0])
                staff_data['summary'] = summary_str
                staff_list.append(staff_data)
            
            report_data_per_jurusan.append({
                'nama_jurusan': data['nama_jurusan'],
                'staff_data': staff_list
            })

        session['report_for_download'] = report_data_per_jurusan
        return render_template('rekap_laporan.html', report_data=report_data_per_jurusan, days_in_month=days_in_month, selected_bulan_formatted=selected_bulan_formatted)

    except Exception as e:
        print(f"Terjadi Internal Server Error di rekap_laporan_view: {e}")
        traceback.print_exc()
        return "Terjadi kesalahan saat memproses laporan.", 500

# --- Rute Download Laporan ---
@app.route('/download_laporan')
def download_laporan():
    if 'user_role' not in session or session['user_role'] != 'Admin':
        return redirect(url_for('login'))

    try:
        # --- LANGKAH 1: KITA PROSES ULANG SEMUA DATA DI SINI ---
        conn = get_db_connection()
        target_month = '2025-07' # Nanti bisa dibuat dinamis
        year, month = map(int, target_month.split('-'))

        all_staff = conn.execute("SELECT nip, nama_lengkap, jurusan, \"detail jurusan\" FROM users WHERE role != 'Admin' ORDER BY jurusan, nama_lengkap").fetchall()
        attendance_data = conn.execute("SELECT * FROM attendance WHERE strftime('%Y-%m', tanggal) = ?", (target_month,)).fetchall()
        approved_clarifications = conn.execute(
            "SELECT nip_pengaju, tanggal_klarifikasi, kategori_surat FROM clarifications WHERE strftime('%Y-%m', tanggal_klarifikasi) = ? AND status_final LIKE 'Disetujui%'", 
            (target_month,)
        ).fetchall()
        conn.close()

        # (Logika pemrosesan data disalin persis dari rekap_laporan_view)
        report_data = {}
        for staff in all_staff:
            jurusan = staff['jurusan']
            detail_jurusan = staff['detail jurusan']
            if jurusan not in report_data:
                report_data[jurusan] = { 'nama_jurusan': detail_jurusan, 'staff_data': {} }
            report_data[jurusan]['staff_data'][staff['nip']] = {
                'nama': staff['nama_lengkap'], 'absensi': {},
                'summary_counts': {'KT': 0, 'PK': 0, 'NF': 0, 'FL': 0, 'CT': 0, 'IZ': 0}
            }
        
        clarif_dict = {(item['nip_pengaju'], item['tanggal_klarifikasi'].split(' ')[0]): item['kategori_surat'] for item in approved_clarifications}

        for record in attendance_data:
            nip = record['nip']
            current_unit_data = next((unit['staff_data'][nip] for unit in report_data.values() if nip in unit['staff_data']), None)
            if not current_unit_data: continue

            try:
                tanggal_obj = datetime.strptime(record['tanggal'], '%Y-%m-%d %H:%M:%S')
                day = tanggal_obj.day
                tanggal_str = tanggal_obj.strftime('%Y-%m-%d')
                status = record['status'] if 'status' in record.keys() else ''
                jam_masuk = record['jam masuk'] if 'jam masuk' in record.keys() else None
                jam_pulang = record['jam pulang'] if 'jam pulang' in record.keys() else None
                keterangan = record['keterangan'] if 'keterangan' in record.keys() else ''
                kode = 'PK'
                if status and "Disetujui" in status:
                    if 'Cuti' in keterangan: kode = 'CT'
                    elif (nip, tanggal_str) in clarif_dict:
                        kategori = clarif_dict.get((nip, tanggal_str))
                        if kategori and 'Non Fleksibel' in kategori: kode = 'NF'
                        elif kategori and 'Fleksibel' in kategori: kode = 'FL'
                        else: kode = 'IZ'
                    else: kode = 'IZ'
                elif jam_masuk and jam_pulang:
                    dur = datetime.strptime(jam_pulang, '%H:%M:%S.%f') - datetime.strptime(jam_masuk, '%H:%M:%S.%f')
                    if dur.total_seconds() >= 4 * 3600: kode = 'KT'
                current_unit_data['absensi'][day] = kode
                current_unit_data['summary_counts'][kode] += 1
            except Exception:
                continue

        report_data_per_jurusan = []
        for jurusan_key, data in report_data.items():
            staff_list = []
            for nip, staff_data in data['staff_data'].items():
                summary_counts = staff_data['summary_counts']
                summary_str = ", ".join([f"{k}:{v}" for k, v in summary_counts.items() if v > 0])
                staff_data['summary'] = summary_str
                staff_list.append(staff_data)
            report_data_per_jurusan.append({ 'nama_jurusan': data['nama_jurusan'], 'staff_data': staff_list })
        
        # --- LANGKAH 2: BUAT FILE EXCEL (Logika ini sudah benar) ---
        output = io.BytesIO()
        writer = pd.ExcelWriter(output, engine='openpyxl')

        for unit_data in report_data_per_jurusan:
            nama_jurusan = unit_data['nama_jurusan']
            staff_list = unit_data['staff_data']
            if not staff_list: continue

            data_for_df = []
            for staff in staff_list:
                row = {'Nama Staf': staff['nama']}
                row.update(staff['absensi'])
                row['Jumlah'] = staff['summary']
                data_for_df.append(row)
            
            df = pd.DataFrame(data_for_df)
            day_columns = [col for col in df.columns if isinstance(col, int)]
            sorted_days = sorted(day_columns)
            column_order = ['Nama Staf'] + sorted_days + ['Jumlah']
            df = df[column_order]

            sheet_name = ''.join(filter(str.isalnum, nama_jurusan))[:31]
            df.to_excel(writer, sheet_name=sheet_name, index=False)

        writer.close()
        output.seek(0)
        
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name='Laporan_Absensi_Bulanan.xlsx'
        )

    except Exception as e:
        print(f"Error saat membuat file Excel: {e}")
        traceback.print_exc()
        flash("Terjadi kesalahan saat membuat file Excel.", "error")
        return redirect(url_for('rekap_laporan_view'))

# --- Rute Riwayat Cuti ---
@app.route('/riwayat_cuti')
def riwayat_cuti():
    # --- PERBAIKAN: Pengecekan peran yang lebih fleksibel ---
    # Sekarang, semua pengguna yang sudah login bisa mengakses halaman ini.
    if 'user_id' not in session:
        return redirect(url_for('login'))

    nip = session['user_id']
    nama_pengguna = session['user_name'] # Menggunakan nama variabel yang lebih umum
    
    conn = get_db_connection()
    # Query ini sudah benar dan universal, tidak perlu diubah.
    cuti_records = conn.execute(
        "SELECT * FROM cuti_dosen WHERE nip = ? ORDER BY tanggal_mulai DESC", 
        (nip,)
    ).fetchall()
    conn.close()

    # Mengirim nama pengguna ke template
    return render_template('riwayat_cuti.html', riwayat=cuti_records, nama_pengguna=nama_pengguna)


# =====================================================================
# FUNGSI BARU YANG AMAN: HANYA UNTUK MELIHAT RIWAYAT CUTI BAWAHAN
# =====================================================================
@app.route('/riwayat_cuti_bawahan/<nip>')
def riwayat_cuti_bawahan(nip):
    # Keamanan: Pastikan yang mengakses adalah seorang pimpinan
    ROLES_APPROVAL = ['Admin', 'Kajur', 'Sekjur', 'Wadir1', 'Wadir2', 'Wadir3', 'Direktur']
    if 'user_role' not in session or session['user_role'] not in ROLES_APPROVAL:
        return "Akses Ditolak", 403

    conn = get_db_connection()
    
    # Ambil nama bawahan untuk ditampilkan di judul halaman
    bawahan = conn.execute("SELECT nama_lengkap FROM users WHERE nip = ?", (nip,)).fetchone()
    if not bawahan:
        conn.close()
        return "Pengguna tidak ditemukan", 404
    
    nama_bawahan = bawahan['nama_lengkap']
    
    # Ambil riwayat cuti dari tabel cuti_dosen untuk NIP bawahan tersebut
    cuti_records = conn.execute(
        "SELECT * FROM cuti_dosen WHERE nip = ? ORDER BY tanggal_mulai DESC", 
        (nip,)
    ).fetchall()
    
    conn.close()

    # Render sebuah template HTML BARU yang didedikasikan untuk ini
    return render_template('riwayat_cuti_bawahan.html', riwayat=cuti_records, nama_bawahan=nama_bawahan)


@app.route('/history')
def history():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    user_nip = session['user_id']
    user_role = session['user_role']
    
    # Definisikan peran mana yang merupakan pimpinan/approver
    ROLES_APPROVAL = ['Kajur', 'Sekjur', 'Wadir1', 'Wadir2', 'Wadir3', 'Direktur', 'Admin']
    
    history_records = []

    if user_role in ROLES_APPROVAL:
        
        # --- LOGIKA SPESIAL UNTUK SEKJUR ---
        if user_role == 'Sekjur':
            # 1. Cari tahu siapa atasan dari Sekjur ini (yaitu NIP Kajur)
            atasan_data = conn.execute("SELECT id_atasan FROM users WHERE nip = ?", (user_nip,)).fetchone()
            
            bawahan = [] # Inisialisasi sebagai list kosong
            if atasan_data and atasan_data['id_atasan']:
                kajur_nip = atasan_data['id_atasan']
                # 2. Ambil daftar bawahan dari KAJUR, bukan dari Sekjur
                bawahan = conn.execute("SELECT nip FROM users WHERE id_atasan = ?", (kajur_nip,)).fetchall()
        
        # --- LOGIKA NORMAL UNTUK PIMPINAN LAINNYA ---
        else:
            # Ambil daftar bawahan langsung dari pimpinan yang login
            bawahan = conn.execute("SELECT nip FROM users WHERE id_atasan = ?", (user_nip,)).fetchall()
        
        # --- LOGIKA BERSAMA UNTUK MENGAMBIL RIWAYAT ---
        list_nip_bawahan = [b['nip'] for b in bawahan]
        
        if list_nip_bawahan:
            placeholders = ', '.join('?' for _ in list_nip_bawahan)
            query = f"SELECT * FROM clarifications WHERE nip_pengaju IN ({placeholders}) ORDER BY tanggal_pengajuan DESC"
            history_records = conn.execute(query, list_nip_bawahan).fetchall()

    else:
        # JIKA STAF BIASA: Ambil riwayat diri sendiri
        history_records = conn.execute(
            "SELECT * FROM clarifications WHERE nip_pengaju = ? ORDER BY tanggal_pengajuan DESC", 
            (user_nip,)
        ).fetchall()

    conn.close()
    return render_template('history.html', records=history_records)


@app.route('/preview_bukti/<int:clarification_id>')
def preview_bukti(clarification_id):
    # Keamanan: Pastikan hanya pengguna yang sudah login yang bisa mengakses
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    klarifikasi = conn.execute(
        "SELECT file_bukti FROM clarifications WHERE id = ?", 
        (clarification_id,)
    ).fetchone()
    conn.close()

    if not klarifikasi or not klarifikasi['file_bukti']:
        flash('File bukti tidak ditemukan.', 'error')
        # Kembali ke halaman sebelumnya jika tidak ada file, aman untuk semua peran
        return redirect(request.referrer or url_for('dashboard_admin'))

    # Menggunakan os.path untuk mendapatkan direktori dan nama file
    # Pastikan app.config['UPLOAD_FOLDER'] sudah di-set di awal script Anda
    directory = app.config['UPLOAD_FOLDER']
    filename = os.path.basename(klarifikasi['file_bukti'])

    # Mengirim file untuk ditampilkan (bukan diunduh)
    return send_from_directory(directory, filename)

@app.route('/download_bukti/<int:clarification_id>')
def download_bukti(clarification_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    klarifikasi = conn.execute(
        "SELECT * FROM clarifications WHERE id = ?", 
        (clarification_id,)
    ).fetchone()
    conn.close()

    if not klarifikasi or not klarifikasi['file_bukti']:
        flash('File bukti tidak ditemukan.', 'error')
        return redirect(request.referrer or url_for('dashboard_admin'))

    # Membuat nama file baru yang deskriptif
    file_path_db = klarifikasi['file_bukti']
    directory = app.config['UPLOAD_FOLDER']
    original_filename = os.path.basename(file_path_db)
    
    nama_pengaju = klarifikasi['nama_lengkap'].replace(' ', '_')
    jenis_surat = klarifikasi['jenis_surat'].replace(' ', '_')
    tanggal_klarifikasi = klarifikasi['tanggal_klarifikasi'].split(' ')[0]
    file_extension = os.path.splitext(original_filename)[1]

    new_filename = f"Bukti_{jenis_surat}_{nama_pengaju}_{tanggal_klarifikasi}{file_extension}"

    # Mengirim file dengan perintah untuk mengunduh (as_attachment=True)
    return send_from_directory(
        directory, 
        original_filename, 
        as_attachment=True, 
        download_name=new_filename
    )

@app.route('/uploads/<path:filename>')
def serve_uploaded_file(filename):
    # Keamanan: Pastikan hanya pengguna yang sudah login yang bisa mengakses file
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    # Mengirim file dari folder UPLOAD_FOLDER untuk ditampilkan di browser
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# if __name__ == '__main__':
#     if not os.path.exists(UPLOAD_FOLDER):
#         os.makedirs(UPLOAD_FOLDER)
#     app.run(debug=True)

# if __name__ == "__main__":
#     # Pastikan folder upload ada
#     if not os.path.exists(app.config["UPLOAD_FOLDER"]):
#         os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

# if __name__ == "__main__":
#     port = int(os.environ.get("PORT", 5000))
#     app.run(host="0.0.0.0", port=port)

    # Baca debug dari ENV
# debug_mode = str(os.environ.get("FLASK_DEBUG", "0")).lower() in ("1", "true", "yes")

    # Port default 5000 (lokal), Railway inject $PORT
# port = int(os.environ.get("PORT", 5000))

if __name__ == "__main__":
    # Hanya untuk lokal development
    if not os.path.exists(app.config["UPLOAD_FOLDER"]):
        os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    debug_mode = str(os.environ.get("FLASK_DEBUG", "0")).lower() in ("1", "true", "yes")
    port = int(os.environ.get("PORT", 5000))

    app.run(host="0.0.0.0", port=port, debug=debug_mode)


# --- 1. KONFIGURASI VAPID KEYS ---
# Letakkan ini di bagian atas app.py, di bawah baris import


# --- VAPID keys (ambil dari environment) ---
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY")
VAPID_PUBLIC_KEY  = os.getenv("VAPID_PUBLIC_KEY")
VAPID_MAILTO      = os.getenv("VAPID_MAILTO", "admin@example.com")
VAPID_CLAIMS = {"sub": f"mailto:{VAPID_MAILTO}"}

@app.route("/vapid_public_key")
def vapid_public_key():
    # hanya return public key — aman untuk diakses client
    if not VAPID_PUBLIC_KEY:
        return jsonify({"error":"VAPID public key not configured"}), 500
    return jsonify({"publicKey": VAPID_PUBLIC_KEY})


# --- 2. ENDPOINT UNTUK MENERIMA DATA SUBSCRIPTION DARI BROWSER ---
@app.route('/api/subscribe', methods=['POST'])
def subscribe():
    # Ambil data subscription dari request JSON
    subscription_data = request.get_json()
    if not subscription_data:
        return jsonify({"error": "No subscription data provided"}), 400

    # Identifikasi user yang sedang login dari session
    user_nip = session.get('user_id') 
    if not user_nip:
        return jsonify({"error": "User not authenticated"}), 401

    try:
        # Simpan data subscription ke database
        conn = sqlite3.connect('database.db')
        conn.row_factory = sqlite3.Row
        subscription_json = json.dumps(subscription_data)
        
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET push_subscription_info = ? WHERE nip = ?", 
                       (subscription_json, user_nip))
        conn.commit()
        conn.close()
        
        print(f"[SUCCESS] Subscription berhasil disimpan untuk NIP: {user_nip}")
        return jsonify({"success": True}), 200

    except Exception as e:
        print(f"[ERROR] Gagal menyimpan subscription: {e}")
        return jsonify({"error": str(e)}), 500

# --- 3. FUNGSI UTAMA UNTUK MENGIRIM NOTIFIKASI ---
def send_push_notification(target_nip, title, body, url="/"):
    """
    Mengirim notifikasi push ke NIP tertentu.
    """
    try:
        # Ambil data subscription user dari database berdasarkan NIP target
        conn = sqlite3.connect('database.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT push_subscription_info FROM users WHERE nip = ?", (target_nip,))
        result = cursor.fetchone()
        conn.close()

        if result and result['push_subscription_info']:
            # Ubah string JSON dari database kembali menjadi dictionary
            subscription_info = json.loads(result['push_subscription_info'])
            
            # Siapkan data payload notifikasi
            payload = {
                "title": title,
                "body": body,
                "url": url
            }

            # Kirim notifikasi menggunakan webpush
            webpush(
                subscription_info=subscription_info,
                data=json.dumps(payload),
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=VAPID_CLAIMS.copy()
            )
            print(f"Push notification sent successfully to NIP: {target_nip}")
            return True
        else:
            print(f"No subscription info found for NIP: {target_nip}")
            return False

    except WebPushException as ex:
        print(f"WebPushException error for NIP {target_nip}: {ex}")
        if ex.response and ex.response.status_code == 410:
            print("Subscription expired or invalid. Consider removing from DB.")
        return False
    except Exception as e:
        print(f"Generic error sending push notification: {e}")
        return False


# --- Service Worker route ---
@app.route('/service-worker.js')
def service_worker():
    return app.send_static_file('service-worker.js')