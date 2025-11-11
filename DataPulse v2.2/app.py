import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import configparser
import json
import sv_ttk
from pymodbus.client import ModbusTcpClient
import threading
import time
from datetime import datetime
import sqlite3
import csv
import os


class ModbusApp:
    def __init__(self, root):
        self.root = root

        # 1. Paletleri ve Config'i oluştur
        self.palettes = {
            'light': {
                'background': '#F5F5F5', 'panel_bg': '#FFFFFF', 'text_main': '#212121',
                'text_subtle': '#757575', 'text_on_color': '#FFFFFF', 'success': '#00A651',
                'danger': '#DC3545', 'warning': '#FD7E14', 'info_accent': '#0066CC',
                'hover': '#007A3D', 'entry_bg': '#E0E0E0', 'entry_focus_bg': '#FFFFFF'
            },
            'dark': {
                'background': '#2B2B2B', 'panel_bg': '#404040', 'text_main': '#F5F5F5',
                'text_subtle': '#9E9E9E', 'text_on_color': '#FFFFFF', 'success': '#00D084',
                'danger': '#FF6B35', 'warning': '#FFC107', 'info_accent': '#4A9EFF',
                'hover': '#4A9EFF', 'entry_bg': '#333333', 'entry_focus_bg': '#555555'
            }
        }
        self.config = configparser.ConfigParser()
        self.config.read('config.ini')

        # 2. Ayarları ve özel renkleri yükle
        self.load_config()
        self._load_custom_colors_from_config()

        # 3. Kalan değişkenleri ve temel temayı ayarla
        self.strings = {}
        self.tag_cache = {}
        self._apply_theme()

        # 4. ÖZEL STİLLERİ TANIMLA (EN KRİTİK ADIM)
        self._update_styles()

        # 5. Dil dosyasını yükle
        self._load_language()

        # --- Geri kalan kurulum işlemleri ---
        if not self.config.has_section('Database'): self.config.add_section('Database')
        if not self.config.has_section('User'): self.config.add_section('User')
        self.database_path = self.config.get('Database', 'last_opened', fallback='modbus_data.db')

        self.modbus_client = None
        self.is_logging_active = False; self.logging_thread = None
        self.is_scanning_active = False; self.scanning_thread = None
        self.last_status = ("", "normal"); self.persistent_status = ("", "error"); self.status_revert_id = None
        self.current_live_view = 'holding'

        self.root.title(self.strings.get('window_title', "Modbus Kontrol Paneli"))
        self.root.geometry(f"{self.width}x{self.height}")
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)

        self._init_database()
        self._load_tags_into_cache()

        # 6. SON OLARAK WIDGET'LARI OLUŞTUR
        self._create_widgets()

        self.persistent_status = (self.strings.get("status_disconnected", "Bağlantı Kapalı."), "error")
        self.update_status(self.persistent_status[0], self.persistent_status[1], is_persistent=True)
        self.root.after(2000, self._periodic_live_view_update)

        # Alarm Değişkenleri
        self.is_alarm_engine_active = False
        self.alarm_engine_thread = None
        self.active_alarms = {}

        # Arama Listeleri
        self.live_tree_items = []
        self.live_tree_item_values = {}
        self.scan_tree_items = []
        self.scan_tree_item_values = {}

    def load_config(self):
        self.server_ip = self.config.get('Connection', 'ip', fallback='127.0.0.1')
        self.server_port = self.config.getint('Connection', 'port', fallback=502)
        self.theme = self.config.get('Appearance', 'theme', fallback='light')
        self.language = self.config.get('Appearance', 'language', fallback='tr')
        self.width = self.config.getint('Window', 'width', fallback=950)
        self.height = self.config.getint('Window', 'height', fallback=700)
        
    def _load_language(self):
        try:
            with open(f"{self.language}.json", 'r', encoding='utf-8') as f: self.strings = json.load(f)
        except FileNotFoundError:
            messagebox.showerror("Dil Hatası", f"'{self.language}.json' dosyası bulunamadı.")
            if self.language != 'en': self.language = 'en'; self._load_language()

    def _apply_theme(self):
        sv_ttk.set_theme(self.theme)

    def _load_custom_colors_from_config(self):
        """Reads custom colors from config.ini and overrides the default palette."""
        for theme_name in ['light', 'dark']:
            section_name = f"Theme_{theme_name.capitalize()}"
            if self.config.has_section(section_name):
                for key, default_value in self.palettes[theme_name].items():
                    config_value = self.config.get(section_name, key, fallback=default_value)
                    self.palettes[theme_name][key] = config_value

    def _update_styles(self):
        """Mevcut temaya ve config.ini'deki renklere göre TÜM stilleri günceller."""
        style = ttk.Style()
        theme = self.theme
        palette = self.palettes[theme]

        # 1. Ana Pencere ve Çerçeveleri Doğrudan Renklendirme (En Önemli Adım)
        # sv_ttk'yı ezmek için hem root'u hem de TFrame'i doğrudan hedefliyoruz.
        self.root.configure(background=palette['background'])
        style.configure('TFrame', background=palette['background'])

        # 2. Notebook ve Sekme Stilleri
        style.configure('TNotebook', background=palette['background'])
        

        # 3. Genel Widget Stilleri (Bunlar zaten vardı, kontrol amaçlı)
        style.configure('.', background=palette['background'], foreground=palette['text_main'])
        style.configure("Treeview",
                        background=palette['panel_bg'],
                        fieldbackground=palette['panel_bg'],
                        foreground=palette['text_main'])
        style.map('Treeview', background=[('selected', palette['info_accent'])])

        # 4. Panel (LabelFrame) Stilleri
        style.configure('TLabelFrame', background=palette['panel_bg'])
        style.configure('TLabelFrame.Label',
                        foreground=palette['info_accent'],
                        font=('Segoe UI', 10, 'bold'),
                        background=palette['panel_bg'])

        # 5. Giriş Kutusu (Entry) Stilleri
        style.configure('TEntry',
                        fieldbackground=palette['entry_bg'],
                        foreground=palette['text_main'],
                        insertcolor=palette['text_main'])
        style.map('TEntry',
            fieldbackground=[('focus', palette['entry_focus_bg'])])
        
        # 6. Alarm Satır Stilleri (Yeni yöntem ile)
        #self._configure_treeview_tags()

       
    def _configure_treeview_tags(self):
        """Alarm tablolarındaki renk etiketlerini doğrudan yapılandırır."""
        palette = self.palettes[self.theme]
        
        # tag_configure metodu, stil motorunu atlayarak doğrudan widget'a stil atar.
        # Bu, sv_ttk gibi kapsamlı temaları ezmek için gereklidir.
        
        # Yüksek Öncelik
        self.active_alarms_tree.tag_configure('Danger.Treeview', background=palette['danger'], foreground=palette['text_on_color'])
        self.alarm_rules_tree.tag_configure('Danger.Treeview', background=palette['danger'], foreground=palette['text_on_color'])
        
        # Orta Öncelik
        warning_fg = palette['text_on_color'] if self.theme == 'dark' else palette['text_main']
        self.active_alarms_tree.tag_configure('Warning.Treeview', background=palette['warning'], foreground=warning_fg)
        self.alarm_rules_tree.tag_configure('Warning.Treeview', background=palette['warning'], foreground=warning_fg)
        
        # Düşük Öncelik
        self.active_alarms_tree.tag_configure('Info.Treeview', background=palette['info_accent'], foreground=palette['text_on_color'])
        self.alarm_rules_tree.tag_configure('Info.Treeview', background=palette['info_accent'], foreground=palette['text_on_color'])

    def _load_tags_into_cache(self):
        self.tag_cache = {}
        try:
            conn = sqlite3.connect(self.database_path)
            cursor = conn.cursor()
            sql = "SELECT c.cihaz_adi, e.etiket_adi, e.modbus_tipi, e.modbus_adresi FROM etiketler e JOIN cihazlar c ON e.fk_cihaz_id = c.cihaz_id"
            cursor.execute(sql)
            tags = cursor.fetchall()
            for cihaz_adi, etiket_adi, modbus_tipi, modbus_adresi in tags:
                key = (modbus_tipi, modbus_adresi)
                self.tag_cache[key] = {'cihaz_adi': cihaz_adi, 'etiket_adi': etiket_adi}
            conn.close()
            print(f"{len(self.tag_cache)} adet etiket hafızaya yüklendi.")
        except Exception as e:
            messagebox.showerror("Etiket Hatası", f"Etiketler veritabanından okunamadı: {e}")

    def _update_all_ui_text(self):
        """TÜM arayüz metinlerini mevcut dile göre anında günceller."""
        try:
            self.root.title(self.strings.get('window_title'))
            self._create_menubar() # Menüyü yeniden oluşturmak en garantili yöntemdir

            # Sekme Başlıkları
            self.notebook.tab(0, text=self.strings.get('tab1_title'))
            self.notebook.tab(1, text=self.strings.get('tab2_title'))
            self.notebook.tab(2, text=self.strings.get('tab3_title'))
            self.notebook.tab(3, text=self.strings.get('tab4_title'))
            self.notebook.tab(4, text=self.strings.get('tab5_title'))

            # --- Sekme 1: Manuel Kontrol ---
            self.tagged_frame.config(text=self.strings.get('tab1_tagged_frame'))
            self.tab1_device_label.config(text=self.strings.get('tab1_device_label'))
            self.tab1_tag_label.config(text=self.strings.get('tab1_tag_label'))
            self.conn_frame.config(text=self.strings.get('conn_frame_title'))
            self.connect_button.config(text=self.strings.get('connect_button'))
            self.disconnect_button.config(text=self.strings.get('disconnect_button'))
            self.hr_frame.config(text=self.strings.get('hr_frame_title'))
            self.hr_addr_label.config(text=self.strings.get('address_label'))
            self.hr_val_label.config(text=self.strings.get('value_label'))
            self.hr_read_btn.config(text=self.strings.get('read_button'))
            self.hr_write_btn.config(text=self.strings.get('write_button'))
            self.reg_read_val_label.config(text=self.strings.get('read_value_label'))
            self.coil_frame.config(text=self.strings.get('coil_frame_title'))
            self.coil_addr_label.config(text=self.strings.get('address_label'))
            self.coil_stat_label.config(text=self.strings.get('status_label'))
            self.coil_read_btn.config(text=self.strings.get('read_button'))
            self.coil_write_btn.config(text=self.strings.get('write_button'))
            self.coil_read_val_label.config(text=self.strings.get('read_status_label'))

            # --- Sekme 2: Veri Görüntüleme & Kayıt ---
            # (Bu sekmede genelde sorun yoktu, yine de kontrol amaçlı eklenmiştir.)
            self.view_select_label.config(text=self.strings.get('tab2_view_select_label'))
            self.coils_view_btn.config(text=self.strings.get('tab2_coils_btn'))
            self.holding_view_btn.config(text=self.strings.get('tab2_holding_btn'))
            self.input_view_btn.config(text=self.strings.get('tab2_input_btn'))
            self.live_data_frame.config(text=self.strings.get('tab2_live_data_frame'))
            self.live_tree.heading("cihaz", text=self.strings.get('tab2_header_device', "Ekipman"))
            self.live_tree.heading("etiket", text=self.strings.get('tab2_header_tag', "Etiket"))
            self.live_tree.heading("adres", text=self.strings.get('tab2_header_address'))
            header_key = 'tab2_header_status' if self.current_live_view == 'coil' else 'tab2_header_value'
            self.live_tree.heading("deger", text=self.strings.get(header_key))
            self.log_settings_frame.config(text=self.strings.get('tab2_log_settings_frame'))
            self.start_log_button.config(text=self.strings.get('tab2_start_log_btn'))
            self.stop_log_button.config(text=self.strings.get('tab2_stop_log_btn'))
            self.log_type_label.config(text=self.strings.get('tab2_log_type_label'))
            self.log_addr_label.config(text=self.strings.get('tab2_log_addr_label'))
            self.log_count_label.config(text=self.strings.get('tab2_log_count_label'))
            self.log_interval_label.config(text=self.strings.get('tab2_log_interval_label'))
            
            # --- Sekme 3: Aktif Portlar ---
            self.scan_settings_frame.config(text=self.strings.get('tab3_scan_settings_frame'))
            self.scan_start_addr_label.config(text=self.strings.get('tab3_start_addr_label'))
            self.scan_end_addr_label.config(text=self.strings.get('tab3_end_addr_label'))
            self.scan_button.config(text=self.strings.get('tab3_start_scan_btn'))
            self.scan_result_frame.config(text=self.strings.get('tab3_results_frame'))
            self.scan_tree.heading("cihaz", text=self.strings.get('tab3_header_device', "Ekipman"))
            self.scan_tree.heading("etiket", text=self.strings.get('tab3_header_tag', "Etiket"))
            self.scan_tree.heading("adres", text=self.strings.get('tab3_header_address'))
            self.scan_tree.heading("tip", text=self.strings.get('tab3_header_type', "Tip"))
            self.scan_tree.heading("deger", text=self.strings.get('tab3_header_value'))

            # --- Sekme 4: Ekipman & Etiketler ---
            # Bir önceki adımdaki düzeltmeler sayesinde bu sekme artık hatasız güncellenecek
            self._update_tab4_texts() # Kod tekrarını önlemek için yardımcı fonksiyona taşıdım.

            # --- Sekme 5: Alarmlar ---
            self.new_alarm_btn.config(text=self.strings.get("tab5_new_alarm_btn"))
            self.edit_alarm_btn.config(text=self.strings.get("tab5_edit_alarm_btn"))
            self.delete_alarm_btn.config(text=self.strings.get("tab5_delete_alarm_btn"))
            self.active_alarms_frame.config(text=self.strings.get("tab5_active_alarms_frame"))
            self.all_rules_frame.config(text=self.strings.get("tab5_all_rules_frame"))
            self.active_alarms_tree.heading("time", text=self.strings.get('tab5_time_header'))
            self.active_alarms_tree.heading("priority", text=self.strings.get('tab5_priority_header'))
            self.active_alarms_tree.heading("tag_name", text=self.strings.get('tab5_tag_header'))
            self.active_alarms_tree.heading("message", text=self.strings.get('tab5_message_header'))
            self.alarm_rules_tree.heading("id", text=self.strings.get('tab5_id_header'))
            self.alarm_rules_tree.heading("tag_name", text=self.strings.get('tab5_tag_header'))
            self.alarm_rules_tree.heading("condition", text=self.strings.get('tab5_condition_header'))
            self.alarm_rules_tree.heading("value", text=self.strings.get('tab5_value_header'))
            self.alarm_rules_tree.heading("priority", text=self.strings.get('tab5_priority_header'))
            self.alarm_rules_tree.heading("is_active", text=self.strings.get('tab5_active_header'))

            # Verileri de yeniden yükleyerek "Evet", "Yüksek" gibi değerlerin çevrilmesini sağla
            self._load_alarm_rules_to_view()

            # Kalıcı durumu da yeni dile göre güncelle
            is_conn = self.modbus_client and self.modbus_client.is_socket_open()
            p_msg_key = "status_connected" if is_conn else "status_disconnected"
            p_type = "success" if is_conn else "error"
            self.persistent_status = (self.strings.get(p_msg_key), p_type)
            if not hasattr(self, 'active_alarms') or not self.active_alarms:
                self.update_status(self.persistent_status[0], self.persistent_status[1], is_persistent=True)

        except Exception as e:
            print(f"Dil güncelleme hatası: {e}")

    def _update_tab4_texts(self):
        """Sekme 4'teki metinleri günceller."""
        if hasattr(self, 'cihazlar_lf'):
            self.cihazlar_lf.config(text=self.strings.get('tab4_devices_label'))
            # --- DÜZELTME: Butonlara doğrudan isimleriyle erişiliyor ---
            self.new_device_btn.config(text=self.strings.get('tab4_new_btn'))
            self.delete_device_btn.config(text=self.strings.get('tab4_delete_btn'))

        if hasattr(self, 'etiket_lf'):
            self.etiket_lf.config(text=self.strings.get('tab4_tags_label'))
            # --- DÜZELTME: Butonlara doğrudan isimleriyle erişiliyor ---
            self.new_tag_btn.config(text=self.strings.get('tab4_new_btn'))
            self.delete_tag_btn.config(text=self.strings.get('tab4_delete_btn'))

        if hasattr(self, 'etiket_tree'):
            self.etiket_tree.heading("id", text=self.strings.get('tab4_col_id'))
            self.etiket_tree.heading("address", text=self.strings.get('tab4_col_address'))
            self.etiket_tree.heading("type", text=self.strings.get('tab4_col_type'))
            self.etiket_tree.heading("name", text=self.strings.get('tab4_col_tag_name'))

    def _create_widgets(self):
        self._create_menubar()
        
        # --- DÜZELTME BURADA BAŞLIYOR ---

        # ÖNCE: Durum çubuğunu oluştur ve pencerenin en ALTINA yerleştir.
        self.status_label = ttk.Label(self.root, text="Durum", relief="sunken", anchor="w", padding=5)
        self.status_label.pack(side="bottom", fill="x")

        # SONRA: Sekmeleri oluştur ve KALAN TÜM ALANI doldurmasını söyle.
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(pady=10, padx=10, fill="both", expand=True)
        
        # --- DÜZELTME BURADA BİTİYOR ---

        # Beş sekme için Frame'leri oluştur
        tab1 = ttk.Frame(self.notebook, padding="10")
        tab2 = ttk.Frame(self.notebook, padding="10")
        tab3 = ttk.Frame(self.notebook, padding="10")
        tab4 = ttk.Frame(self.notebook, padding="10")
        tab5 = ttk.Frame(self.notebook, padding="10")
        
        # Sekmeleri Notebook'a ekle
        self.notebook.add(tab1, text=self.strings.get('tab1_title', "Manuel Kontrol"))
        self.notebook.add(tab2, text=self.strings.get('tab2_title', "Veri Görüntüleme & Kayıt"))
        self.notebook.add(tab3, text=self.strings.get('tab3_title', "Aktif Portlar"))
        self.notebook.add(tab4, text=self.strings.get('tab4_title', "Ekipman & Etiketler"))
        self.notebook.add(tab5, text=self.strings.get('tab5_title', "Alarmlar"))
        
        # Her sekmenin içeriğini doldur
        self._create_tab1_content(tab1)
        self._create_tab2_content(tab2)
        self._create_tab3_content(tab3)
        self._create_tab4_content(tab4)
        self._create_tab5_content(tab5)

    def _create_menubar(self):
        if hasattr(self, 'menubar'): self.menubar.destroy()
        self.menubar = tk.Menu(self.root); self.root.config(menu=self.menubar)
        self.file_menu = tk.Menu(self.menubar, tearoff=0); self.menubar.add_cascade(label=self.strings.get('menu_record'), menu=self.file_menu)
        self.file_menu.add_command(label=self.strings.get('menu_record_new'), command=self._new_database)
        self.file_menu.add_command(label=self.strings.get('menu_record_open'), command=self._open_database)
        self.file_menu.add_separator(); self.file_menu.add_command(label=self.strings.get('menu_record_export'), command=self.export_to_csv)
        # Exit satırı kaldırıldı
        self.settings_menu = tk.Menu(self.menubar, tearoff=0); self.menubar.add_cascade(label=self.strings.get('menu_settings'), menu=self.settings_menu)
        self.settings_menu.add_command(label=self.strings.get('menu_settings_app'), command=self.open_settings_window)
        self.help_menu = tk.Menu(self.menubar, tearoff=0); self.menubar.add_cascade(label=self.strings.get('menu_help'), menu=self.help_menu)
        self.help_menu.add_command(label=self.strings.get('menu_help_usage'), command=self.show_help_dialog)
        self.help_menu.add_command(label=self.strings.get('menu_help_about'), command=self.show_about_dialog)

    def _create_tab1_content(self, parent_tab):
        """SEKME 1: Manuel Kontrol - Yeniden Düzenlenmiş Sezgisel Arayüz"""
        
        # --- Ana Sekmenin Grid Yapılandırması ---
        # Üstte iki sütun, altta tek bir geniş satır olacak.
        parent_tab.columnconfigure(0, weight=1)
        parent_tab.columnconfigure(1, weight=1)
        parent_tab.rowconfigure(1, weight=1) # Alt bölüm dikeyde genişlesin

        # ================= ÜST BÖLÜM =================

        # --- Etiketli Hızlı Seçim (SOL ÜST) ---
        self.tagged_frame = ttk.LabelFrame(
            parent_tab,
            text=self.strings.get("tab1_tagged_frame", "Etiketli Kontrol (Hızlı Seçim)"),
            padding="10"
        )
        self.tagged_frame.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        self.tagged_frame.columnconfigure(1, weight=1)

        self.tab1_device_label = ttk.Label(self.tagged_frame, text=self.strings.get("tab1_device_label", "Ekipman:"))
        self.tab1_device_label.grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.device_combo = ttk.Combobox(self.tagged_frame, state="readonly", width=25)
        self.device_combo.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        self.device_combo.bind('<<ComboboxSelected>>', self._on_device_combo_select)
    
        self.tab1_tag_label = ttk.Label(self.tagged_frame, text=self.strings.get("tab1_tag_label", "Etiket:"))
        self.tab1_tag_label.grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.tag_combo = ttk.Combobox(self.tagged_frame, state="readonly", width=25)
        self.tag_combo.grid(row=1, column=1, padx=5, pady=5, sticky="ew")
        self.tag_combo.bind('<<ComboboxSelected>>', self._on_tag_combo_select)
    
        # --- Bağlantı Kontrolü (SAĞ ÜST) ---
        self.conn_frame = ttk.LabelFrame(
            parent_tab, text=self.strings.get('conn_frame_title', "Bağlantı"), padding="10"
        )
        self.conn_frame.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")

        conn_button_frame = ttk.Frame(self.conn_frame)
        conn_button_frame.pack(expand=True) # Butonları dikeyde ortalamak için
        self.connect_button = ttk.Button(
            conn_button_frame, text=self.strings.get('connect_button', "Bağlan"),
            command=self.connect_to_server
        )
        self.connect_button.pack(side="left", padx=5)
        self.disconnect_button = ttk.Button(
            conn_button_frame, text=self.strings.get('disconnect_button', "Bağlantıyı Kes"),
            command=self.disconnect_from_server
        )
        self.disconnect_button.pack(side="left", padx=5)

        # ================= ALT BÖLÜM =================

        # --- Manuel Giriş Paneli (Tüm Alt Alanı Kaplayan Ana Çerçeve) ---
        manual_entry_frame = ttk.LabelFrame(parent_tab, text="Manuel Giriş", padding="10")
        manual_entry_frame.grid(row=1, column=0, columnspan=2, padx=10, pady=10, sticky="nsew")
        manual_entry_frame.columnconfigure(0, weight=1) # İçindeki elemanların yatayda genişlemesi için

        # --- Holding Register Kontrolü (Manuel Panel İçinde - Üstte) ---
        self.hr_frame = ttk.LabelFrame(
            manual_entry_frame, text=self.strings.get('hr_frame_title', "Holding Register"), padding="10"
        )
        self.hr_frame.grid(row=0, column=0, pady=(0, 10), sticky="ew")
        self.hr_frame.columnconfigure(1, weight=1)
        self.hr_frame.columnconfigure(3, weight=1)
        
        self.hr_addr_label = ttk.Label(self.hr_frame, text=self.strings.get('address_label', "Adres"))
        self.hr_addr_label.grid(row=0, column=0, padx=5, pady=5)
        self.hr_addr_entry = ttk.Entry(self.hr_frame, width=8)
        self.hr_addr_entry.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        self.hr_val_label = ttk.Label(self.hr_frame, text=self.strings.get('value_label', "Değer"))
        self.hr_val_label.grid(row=0, column=2, padx=5, pady=5)
        self.hr_val_entry = ttk.Entry(self.hr_frame, width=10)
        self.hr_val_entry.grid(row=0, column=3, padx=5, pady=5, sticky="ew")
    
        hr_button_frame = ttk.Frame(self.hr_frame)
        hr_button_frame.grid(row=1, column=0, columnspan=4, pady=5)
        self.hr_read_btn = ttk.Button(hr_button_frame, text=self.strings.get('read_button', "Oku"), command=self.read_holding_register)
        self.hr_read_btn.pack(side="left", padx=10)
        self.hr_write_btn = ttk.Button(hr_button_frame, text=self.strings.get('write_button', "Yaz"), command=self.write_holding_register)
        self.hr_write_btn.pack(side="left", padx=10)
    
        self.reg_read_val_label = ttk.Label(self.hr_frame, text=self.strings.get('read_value_label', "Okunan Değer"))
        self.reg_read_val_label.grid(row=2, column=0, columnspan=4)
    
        # --- Coil Kontrolü (Manuel Panel İçinde - Altta) ---
        self.coil_frame = ttk.LabelFrame(
            manual_entry_frame, text=self.strings.get('coil_frame_title', "Coil"), padding="10"
        )
        self.coil_frame.grid(row=1, column=0, sticky="ew")
        self.coil_frame.columnconfigure(1, weight=1)
        self.coil_frame.columnconfigure(3, weight=1)
    
        self.coil_addr_label = ttk.Label(self.coil_frame, text=self.strings.get('address_label', "Adres"))
        self.coil_addr_label.grid(row=0, column=0, padx=5, pady=5)
        self.coil_addr_entry = ttk.Entry(self.coil_frame, width=8)
        self.coil_addr_entry.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        self.coil_stat_label = ttk.Label(self.coil_frame, text=self.strings.get('status_label', "Durum"))
        self.coil_stat_label.grid(row=0, column=2, padx=5, pady=5)
        self.coil_val_combo = ttk.Combobox(self.coil_frame, values=["True", "False"], width=7, state="readonly")
        self.coil_val_combo.grid(row=0, column=3, padx=5, pady=5, sticky="ew")
        self.coil_val_combo.set("True")
    
        coil_button_frame = ttk.Frame(self.coil_frame)
        coil_button_frame.grid(row=1, column=0, columnspan=4, pady=5)
        self.coil_read_btn = ttk.Button(coil_button_frame, text=self.strings.get('read_button', "Oku"), command=self.read_coil)
        self.coil_read_btn.pack(side="left", padx=10)
        self.coil_write_btn = ttk.Button(coil_button_frame, text=self.strings.get('write_button', "Yaz"), command=self.write_coil)
        self.coil_write_btn.pack(side="left", padx=10)
    
        self.coil_read_val_label = ttk.Label(self.coil_frame, text=self.strings.get('read_status_label', "Okunan Durum"))
        self.coil_read_val_label.grid(row=2, column=0, columnspan=4)
        
        self._populate_device_combobox()


    def _populate_device_combobox(self):
        """Veritabanındaki TÜM cihazları Hızlı Seçim menüsüne doldurur."""
        try:
            if hasattr(self, 'device_combo'):
                conn = sqlite3.connect(self.database_path)
                cursor = conn.cursor()
                cursor.execute("SELECT cihaz_adi FROM cihazlar ORDER BY cihaz_adi")
                devices = cursor.fetchall()
                # fetchall liste içinde tuple döner, [(isim,), (isim2,)] -> [isim, isim2]
                device_names = [device[0] for device in devices]
                self.device_combo['values'] = device_names
                conn.close()
        except tk.TclError:
            pass
        except Exception as e:
            print(f"Device combobox doldurulamadı: {e}")

    def _on_device_combo_select(self, event=None):
        """Ekipman seçildiğinde, o ekipmana ait etiketleri ikinci menüye doldurur."""
        selected_device = self.device_combo.get()
        self.tag_combo.set('')
        self.tag_combo['values'] = []
        
        tags_for_device = []
        for key, value in self.tag_cache.items():
            if value['cihaz_adi'] == selected_device:
                tags_for_device.append(value['etiket_adi'])
        
        self.tag_combo['values'] = sorted(tags_for_device)

    def _on_tag_combo_select(self, event=None):
        """Etiket seçildiğinde, ilgili adres kutucuğunu otomatik doldurur ve okuma yapar."""
        selected_device = self.device_combo.get()
        selected_tag = self.tag_combo.get()

        if not all([selected_device, selected_tag]): return

        for key, value in self.tag_cache.items():
            if value['cihaz_adi'] == selected_device and value['etiket_adi'] == selected_tag:
                modbus_tipi, modbus_adresi = key

                # --- DÜZELTME: 'reg_' ile başlayan hatalı isimler 'hr_' olarak düzeltildi ---
                self.hr_addr_entry.delete(0, tk.END)
                self.hr_val_entry.delete(0, tk.END)
                self.coil_addr_entry.delete(0, tk.END)
                self.reg_read_val_label.config(text=self.strings.get('read_value_label'))
                self.coil_read_val_label.config(text=self.strings.get('read_status_label'))

                if modbus_tipi == "Coil":
                    self.coil_addr_entry.insert(0, str(modbus_adresi))
                    self.read_coil()
                elif modbus_tipi == "Holding Reg.":
                    self.hr_addr_entry.insert(0, str(modbus_adresi)) # 'reg_' -> 'hr_'
                    self.read_holding_register()
                elif modbus_tipi == "Input Reg.":
                    self.hr_addr_entry.insert(0, str(modbus_adresi)) # 'reg_' -> 'hr_'
                    self.read_input_register()
                return
            
    def read_coil(self):
        if not self.check_connection(): return
        try:
            addr = int(self.coil_addr_entry.get())
            result = self.modbus_client.read_coils(address=addr, count=1)
            if not result.isError():
                status = result.bits[0]
                self.coil_read_val_label.config(text=f"Okunan Durum: < {status} >")
                self.coil_val_combo.set(str(status)) # Combobox'ı da güncelle
                self.update_status(f"Adres {addr} (Coil) okundu.", "normal")
            else:
                messagebox.showerror("Hata", "Coil okunamadı.")
                self.coil_read_val_label.config(text="Okunan Durum: < HATA >")
        except Exception as e:
            messagebox.showerror("Hata", f"Geçersiz giriş veya hata: {e}")
            
    def read_input_register(self):
        """YENİ: Input register'ları okumak için özel fonksiyon."""
        if not self.check_connection(): return
        try:
            addr = int(self.reg_addr_entry.get())
            result = self.modbus_client.read_input_registers(address=addr, count=1)
            if not result.isError():
                value = result.registers[0]
                self.reg_val_entry.delete(0, tk.END)
                self.reg_val_entry.insert(0, str(value))
                self.reg_read_val_label.config(text=f"Okunan Değer: < {value} >")
                self.update_status(f"Adres {addr} (Input Reg) okundu.", "normal")
            else:
                messagebox.showerror("Hata", "Input Register okunamadı.")
                self.reg_read_val_label.config(text="Okunan Değer: < HATA >")
        except Exception as e:
            messagebox.showerror("Hata", f"Geçersiz giriş veya hata: {e}")

    def _create_tab2_content(self, parent_tab):
        parent_tab.columnconfigure(0, weight=1); parent_tab.rowconfigure(1, weight=1)
        view_select_frame = ttk.Frame(parent_tab)
        view_select_frame.grid(row=0, column=0, pady=5, sticky="ew")
        self.view_select_label = ttk.Label(view_select_frame, text=self.strings.get('tab2_view_select_label'))
        self.view_select_label.pack(side="left", padx=5)
        self.coils_view_btn = ttk.Button(view_select_frame, text=self.strings.get('tab2_coils_btn'), command=lambda: self._update_live_view('coil'))
        self.coils_view_btn.pack(side="left", padx=5)
        self.holding_view_btn = ttk.Button(view_select_frame, text=self.strings.get('tab2_holding_btn'), command=lambda: self._update_live_view('holding'))
        self.holding_view_btn.pack(side="left", padx=5)
        self.input_view_btn = ttk.Button(view_select_frame, text=self.strings.get('tab2_input_btn'), command=lambda: self._update_live_view('input'))
        self.input_view_btn.pack(side="left", padx=5)

        self.live_data_frame = ttk.LabelFrame(parent_tab, text=self.strings.get('tab2_live_data_frame'), padding="10")
        self.live_data_frame.grid(row=1, column=0, sticky="nsew")
        self.live_data_frame.columnconfigure(0, weight=1); self.live_data_frame.rowconfigure(0, weight=1)
        
        # --- DÜZELTME BAŞLANGICI: Sütunlar artık burada tanımlanıyor ---
        live_columns = ("cihaz", "etiket", "adres", "deger")
        self.live_tree = ttk.Treeview(self.live_data_frame, columns=live_columns, show="headings")

        # Başlıkları ve sütun genişliklerini en başta ata
        self.live_tree.heading("cihaz", text=self.strings.get('tab2_header_device', "Ekipman"))
        self.live_tree.heading("etiket", text=self.strings.get('tab2_header_tag', "Etiket"))
        self.live_tree.heading("adres", text=self.strings.get('tab2_header_address', "Adres"))
        self.live_tree.heading("deger", text=self.strings.get('tab2_header_value', "Değer")) # Varsayılan başlık
        self.live_tree.column("cihaz", width=120)
        self.live_tree.column("etiket", width=120)
        self.live_tree.column("adres", width=60, anchor='center')
        self.live_tree.column("deger", width=100, anchor='center')
        # --- DÜZELTME SONU ---
        
        self.live_tree.pack(fill="both", expand=True)

        self.log_settings_frame = ttk.LabelFrame(parent_tab, text=self.strings.get('tab2_log_settings_frame'), padding="10")
        self.log_settings_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=10)
        self.start_log_button = ttk.Button(self.log_settings_frame, text=self.strings.get('tab2_start_log_btn'), command=self.start_logging)
        self.start_log_button.pack(side="left", padx=5)
        self.stop_log_button = ttk.Button(self.log_settings_frame, text=self.strings.get('tab2_stop_log_btn'), command=self.stop_logging, state="disabled")
        self.stop_log_button.pack(side="left", padx=5)
        self.log_type_label = ttk.Label(self.log_settings_frame, text=self.strings.get('tab2_log_type_label'))
        self.log_type_label.pack(side="left", padx=(20,5))
        self.log_type_combo = ttk.Combobox(self.log_settings_frame, values=["Input Reg.", "Holding Reg.", "Coil"], width=12, state="readonly")
        self.log_type_combo.pack(side="left"); self.log_type_combo.set("Input Reg.")
        self.log_addr_label = ttk.Label(self.log_settings_frame, text=self.strings.get('tab2_log_addr_label'))
        self.log_addr_label.pack(side="left", padx=(10, 5))
        self.log_addr_entry = ttk.Entry(self.log_settings_frame, width=6)
        self.log_addr_entry.pack(side="left"); self.log_addr_entry.insert(0, "0")
        self.log_count_label = ttk.Label(self.log_settings_frame, text=self.strings.get('tab2_log_count_label'))
        self.log_count_label.pack(side="left", padx=(10, 5))
        self.log_count_entry = ttk.Entry(self.log_settings_frame, width=5)
        self.log_count_entry.pack(side="left"); self.log_count_entry.insert(0, "10")
        self.log_interval_label = ttk.Label(self.log_settings_frame, text=self.strings.get('tab2_log_interval_label'))
        self.log_interval_label.pack(side="left", padx=(10, 5))
        self.log_interval_entry = ttk.Entry(self.log_settings_frame, width=5)
        self.log_interval_entry.pack(side="left"); self.log_interval_entry.insert(0, "10")

    
    def _create_tab3_content(self, parent_tab):
        parent_tab.columnconfigure(0, weight=1); parent_tab.rowconfigure(2, weight=1)
        
        self.scan_settings_frame = ttk.LabelFrame(parent_tab, text=self.strings.get('tab3_scan_settings_frame'), padding="10")
        self.scan_settings_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        self.scan_start_addr_label = ttk.Label(self.scan_settings_frame, text=self.strings.get('tab3_start_addr_label')); self.scan_start_addr_label.pack(side="left", padx=5)
        self.scan_start_addr_entry = ttk.Entry(self.scan_settings_frame, width=6); self.scan_start_addr_entry.pack(side="left", padx=5); self.scan_start_addr_entry.insert(0, "0")
        self.scan_end_addr_label = ttk.Label(self.scan_settings_frame, text=self.strings.get('tab3_end_addr_label')); self.scan_end_addr_label.pack(side="left", padx=5)
        self.scan_end_addr_entry = ttk.Entry(self.scan_settings_frame, width=6); self.scan_end_addr_entry.pack(side="left", padx=5); self.scan_end_addr_entry.insert(0, "199")
        
        action_frame = ttk.Frame(parent_tab)
        action_frame.grid(row=1, column=0, pady=5, padx=10, sticky="ew")

        self.scan_button = ttk.Button(action_frame, text=self.strings.get('tab3_start_scan_btn'), command=self.start_scanning)
        self.scan_button.pack(side="left")

        self.scan_search_button = ttk.Button(action_frame, text="Ara", command=self._search_scan_results, state="disabled")
        self.scan_search_button.pack(side="right", padx=(5,0))
        
        self.scan_search_var = tk.StringVar()
        self.scan_search_entry = ttk.Entry(action_frame, textvariable=self.scan_search_var, width=35, state="disabled")

        # --- DÜZELTME BU SATIRDA ---
        # Arama kutusunun yatayda genişlemesini önlemek için 'fill' ve 'expand' kaldırıldı.
        self.scan_search_entry.pack(side="right", padx=(15, 0))
        # --- BİTTİ ---
        
        self.scan_search_entry.bind("<Return>", self._search_scan_results)
        ttk.Label(action_frame, text="Ara:").pack(side="right")

        self.scan_result_frame = ttk.LabelFrame(parent_tab, text=self.strings.get('tab3_results_frame'), padding="10")
        self.scan_result_frame.grid(row=2, column=0, sticky="nsew", pady=(0,10), padx=10)
        self.scan_result_frame.columnconfigure(0, weight=1); self.scan_result_frame.rowconfigure(0, weight=1)
        
        scan_columns = ("cihaz", "etiket", "adres", "tip", "deger")
        self.scan_tree = ttk.Treeview(self.scan_result_frame, columns=scan_columns, show="headings")
        self.scan_tree.heading("cihaz", text=self.strings.get("tab3_header_device", "Ekipman"))
        self.scan_tree.heading("etiket", text=self.strings.get("tab3_header_tag", "Etiket"))
        self.scan_tree.heading("adres", text=self.strings.get("tab3_header_address", "Adres"))
        self.scan_tree.heading("tip", text=self.strings.get("tab3_header_type", "Tip"))
        self.scan_tree.heading("deger", text=self.strings.get("tab3_header_value", "Değer / Durum"))
        self.scan_tree.column("cihaz", width=120); self.scan_tree.column("etiket", width=140); self.scan_tree.column("adres", width=80)
        self.scan_tree.column("tip", width=100); self.scan_tree.column("deger", width=100, anchor='center')
        self.scan_tree.grid(row=0, column=0, sticky="nsew")
        
        scan_scrollbar = ttk.Scrollbar(self.scan_result_frame, orient="vertical", command=self.scan_tree.yview)
        self.scan_tree.configure(yscrollcommand=scan_scrollbar.set); scan_scrollbar.grid(row=0, column=1, sticky="ns")


    def _create_tab4_content(self, parent_tab):
        parent_tab.columnconfigure(1, weight=1) 
        parent_tab.columnconfigure(0, weight=1) 
        parent_tab.rowconfigure(0, weight=1)

        # --- Sol Bölüm: Ekipmanlar ---
        left_frame = ttk.Frame(parent_tab)
        left_frame.grid(row=0, column=0, sticky="nsew", padx=(10, 5), pady=10)
        left_frame.rowconfigure(1, weight=1)
        left_frame.columnconfigure(0, weight=1)
        
        self.cihazlar_lf = ttk.LabelFrame(left_frame, text=self.strings.get("tab4_devices_label", "Ekipmanlar"))
        self.cihazlar_lf.grid(row=0, column=0, sticky="ew", pady=(0,5))
        
        # --- DÜZELTME: Butonlar artık 'self' ile başlıyor ---
        self.new_device_btn = ttk.Button(self.cihazlar_lf, text=self.strings.get("tab4_new_btn", "Yeni Ekle"), command=self._add_device)
        self.new_device_btn.pack(side="left", padx=5, pady=5)
        self.delete_device_btn = ttk.Button(self.cihazlar_lf, text=self.strings.get("tab4_delete_btn", "Sil"), command=self._delete_device)
        self.delete_device_btn.pack(side="left", padx=5, pady=5)

        devices_tree_frame = ttk.Frame(left_frame)
        devices_tree_frame.grid(row=1, column=0, sticky="nsew")
        devices_tree_frame.rowconfigure(0, weight=1)
        devices_tree_frame.columnconfigure(0, weight=1)

        self.cihaz_listbox = tk.Listbox(devices_tree_frame, exportselection=False)
        cihaz_scrollbar = ttk.Scrollbar(devices_tree_frame, orient="vertical", command=self.cihaz_listbox.yview)
        self.cihaz_listbox.configure(yscrollcommand=cihaz_scrollbar.set)
        
        self.cihaz_listbox.grid(row=0, column=0, sticky="nsew")
        cihaz_scrollbar.grid(row=0, column=1, sticky="ns")
        self.cihaz_listbox.bind('<<ListboxSelect>>', self._on_device_select)

        # --- Sağ Bölüm: Seçili Ekipmanın Etiketleri ---
        right_frame = ttk.Frame(parent_tab)
        right_frame.grid(row=0, column=1, sticky="nsew", padx=(5, 10), pady=10)
        right_frame.rowconfigure(1, weight=1)
        right_frame.columnconfigure(0, weight=1)

        self.etiket_lf = ttk.LabelFrame(right_frame, text=self.strings.get("tab4_tags_label", "Etiketler"))
        self.etiket_lf.grid(row=0, column=0, sticky="ew", pady=(0,5))

        # --- DÜZELTME: Butonlar artık 'self' ile başlıyor ---
        self.new_tag_btn = ttk.Button(self.etiket_lf, text=self.strings.get("tab4_new_btn", "Yeni Ekle"), command=self._add_tag)
        self.new_tag_btn.pack(side="left", padx=5, pady=5)
        self.delete_tag_btn = ttk.Button(self.etiket_lf, text=self.strings.get("tab4_delete_btn", "Sil"), command=self._delete_tag)
        self.delete_tag_btn.pack(side="left", padx=5, pady=5)
        
        tags_tree_frame = ttk.Frame(right_frame)
        tags_tree_frame.grid(row=1, column=0, sticky="nsew")
        tags_tree_frame.rowconfigure(0, weight=1)
        tags_tree_frame.columnconfigure(0, weight=1)

        tag_cols = ("id", "address", "type", "name")
        self.etiket_tree = ttk.Treeview(tags_tree_frame, columns=tag_cols, show="headings")
        self.etiket_tree.heading("id", text=self.strings.get("tab4_col_id", "ID"))
        self.etiket_tree.heading("address", text=self.strings.get("tab4_col_address", "Adres"))
        self.etiket_tree.heading("type", text=self.strings.get("tab4_col_type", "Tip"))
        self.etiket_tree.heading("name", text=self.strings.get("tab4_col_tag_name", "Etiket Adı"))
        self.etiket_tree.column("id", width=50, anchor='center')
        self.etiket_tree.column("address", width=80, anchor='center')
        self.etiket_tree.column("type", width=120)
        self.etiket_tree.column("name", width=200)

        tag_scrollbar = ttk.Scrollbar(tags_tree_frame, orient="vertical", command=self.etiket_tree.yview)
        self.etiket_tree.configure(yscrollcommand=tag_scrollbar.set)
        
        self.etiket_tree.grid(row=0, column=0, sticky="nsew")
        tag_scrollbar.grid(row=0, column=1, sticky="ns")

        self._load_devices_to_listbox()


    def _create_tab5_content(self, parent_tab):
        """SEKME 5: Alarmlar - NameError Düzeltilmiş Hali"""
        parent_tab.columnconfigure(0, weight=1)
        parent_tab.rowconfigure(1, weight=1)
        parent_tab.rowconfigure(3, weight=1)

        self.alarm_buttons_frame = ttk.Frame(parent_tab)
        self.alarm_buttons_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=5)

        self.new_alarm_btn = ttk.Button(self.alarm_buttons_frame, text=self.strings.get("tab5_new_alarm_btn", "Yeni Alarm Ekle"), command=self._add_alarm_rule)
        self.new_alarm_btn.pack(side="left", padx=5)
        self.edit_alarm_btn = ttk.Button(self.alarm_buttons_frame, text=self.strings.get("tab5_edit_alarm_btn", "Seçileni Düzenle"), command=self._edit_alarm_rule)
        self.edit_alarm_btn.pack(side="left", padx=5)
        self.delete_alarm_btn = ttk.Button(self.alarm_buttons_frame, text=self.strings.get("tab5_delete_alarm_btn", "Seçileni Sil"), command=self._delete_alarm_rule)
        self.delete_alarm_btn.pack(side="left", padx=5)

        self.active_alarms_frame = ttk.LabelFrame(parent_tab, text=self.strings.get("tab5_active_alarms_frame", "Aktif Alarmlar"), padding="10")
        self.active_alarms_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)
        self.active_alarms_frame.columnconfigure(0, weight=1); self.active_alarms_frame.rowconfigure(0, weight=1)

        columns = ("time", "priority", "tag_name", "message")
        self.active_alarms_tree = ttk.Treeview(self.active_alarms_frame, columns=columns, show="headings")
        self.active_alarms_tree.heading("time", text=self.strings.get("tab5_col_time", "Zaman"))
        self.active_alarms_tree.heading("priority", text=self.strings.get("tab5_col_priority", "Öncelik"))
        self.active_alarms_tree.heading("tag_name", text=self.strings.get("tab5_col_tag_name", "Etiket Adı"))
        self.active_alarms_tree.heading("message", text=self.strings.get("tab5_col_message", "Mesaj"))
        self.active_alarms_tree.pack(fill="both", expand=True)

        self.all_rules_frame = ttk.LabelFrame(parent_tab, text=self.strings.get("tab5_all_rules_frame", "Tanımlanmış Tüm Alarm Kuralları"), padding="10")
        self.all_rules_frame.grid(row=3, column=0, sticky="nsew", padx=10, pady=10)
        self.all_rules_frame.columnconfigure(0, weight=1); self.all_rules_frame.rowconfigure(0, weight=1)

        rules_cols = ("id", "tag_name", "condition", "value", "priority", "is_active")
        self.alarm_rules_tree = ttk.Treeview(self.all_rules_frame, columns=rules_cols, show="headings")
        self.alarm_rules_tree.heading("id", text=self.strings.get("tab5_col_id", "ID"))
        self.alarm_rules_tree.heading("tag_name", text=self.strings.get("tab5_col_tag_name", "Etiket Adı"))
        self.alarm_rules_tree.heading("condition", text=self.strings.get("tab5_col_condition", "Koşul"))
        self.alarm_rules_tree.heading("value", text=self.strings.get("tab5_col_value", "Değer"))
        self.alarm_rules_tree.heading("priority", text=self.strings.get("tab5_col_priority", "Öncelik"))
        self.alarm_rules_tree.heading("is_active", text=self.strings.get("tab5_col_active", "Aktif mi?"))
        self.alarm_rules_tree.grid(row=0, column=0, sticky="nsew")

        # --- DÜZELTME BU SATIRDA ---
        # Scrollbar'ın parent'ı 'all_rules_frame' yerine 'self.all_rules_frame' olarak düzeltildi.
        rules_scrollbar = ttk.Scrollbar(self.all_rules_frame, orient="vertical", command=self.alarm_rules_tree.yview)
        # --- BİTTİ ---
        
        self.alarm_rules_tree.configure(yscrollcommand=rules_scrollbar.set); rules_scrollbar.grid(row=0, column=1, sticky="ns")

        self._load_alarm_rules_to_view()
       
        self.alarm_rules_tree.configure(yscrollcommand=rules_scrollbar.set); rules_scrollbar.grid(row=0, column=1, sticky="ns")

        self._load_alarm_rules_to_view()
        
        self._configure_treeview_tags()

    def _search_scan_results(self, event=None):
        """Tarama sonuçları tablosundaki verileri filtreler."""
        query = self.scan_search_var.get().lower()

        # Arama kutusu boşsa, tüm satırları yeniden göster
        if not query:
            # Önce listedeki mevcut tüm satırları sil
            for item_id in self.scan_tree.get_children():
                self.scan_tree.detach(item_id)
            # Orijinal listedeki her şeyi geri ekle
            for item_id in self.scan_tree_items:
                self.scan_tree.move(item_id, "", "end")
            return

        # Arama kutusunda metin varsa filtrele
        for item_id in self.scan_tree_items:
            item_values = self.scan_tree_item_values.get(item_id, [])
            match_found = any(query in str(val).lower() for val in item_values)

            if not match_found and self.scan_tree.exists(item_id):
                self.scan_tree.detach(item_id)
            elif match_found and not self.scan_tree.exists(item_id):
                self.scan_tree.move(item_id, "", "end")
    
    def _load_alarm_rules_to_view(self):
        """Veritabanındaki tüm alarm kurallarını okur ve alttaki tabloyu renklendirerek/çevirerek doldurur."""
        for item in self.alarm_rules_tree.get_children():
            self.alarm_rules_tree.delete(item)
        try:
            # 1. Metinleri çevirmek için kullanılacak harita
            priority_translation_map = {
                "Yüksek": self.strings.get("priority_high", "High"),
                "Orta": self.strings.get("priority_medium", "Medium"),
                "Düşük": self.strings.get("priority_low", "Low")
            }

            # 2. Renk stilini bulmak için kullanılacak harita (Anahtarlar sabit!)
            priority_tag_map = {
                "Yüksek": "Danger.Treeview",
                "Orta": "Warning.Treeview",
                "Düşük": "Info.Treeview"
            }

            conn = sqlite3.connect(self.database_path)
            cursor = conn.cursor()
            sql = """SELECT r.kural_id, c.cihaz_adi || '.' || t.etiket_adi, r.kosul, r.tetikleme_degeri, r.oncelik, r.aktif_mi
                     FROM alarm_kurallari r
                     JOIN etiketler t ON r.fk_etiket_id = t.etiket_id
                     JOIN cihazlar c ON t.fk_cihaz_id = c.cihaz_id
                     ORDER BY r.kural_id"""
            cursor.execute(sql)
            rules = cursor.fetchall()
            for rule in rules:
                is_active_str = self.strings.get("generic_yes") if rule[5] == 1 else self.strings.get("generic_no")

                # Veritabanından gelen ham değeri al (örn: "Yüksek")
                raw_priority = rule[4]

                # Ekranda gösterilecek metni çevir
                display_priority = priority_translation_map.get(raw_priority, raw_priority)

                # Rengi belirlemek için stil etiketini bul
                tag_to_apply = (priority_tag_map.get(raw_priority),)

                self.alarm_rules_tree.insert("", "end", 
                                             values=(rule[0], rule[1], rule[2], rule[3], display_priority, is_active_str),
                                             tags=tag_to_apply)
            conn.close()
        except Exception as e:
            messagebox.showerror("Hata", f"Alarm kuralları yüklenemedi: {e}", parent=self.root)

    def _add_alarm_rule(self):
        """Yeni alarm kuralı eklemek için akıllı bir pop-up pencere açar."""
        add_alarm_win = tk.Toplevel(self.root)
        add_alarm_win.title("Yeni Alarm Kuralı Ekle")
        add_alarm_win.transient(self.root)
        add_alarm_win.resizable(False, False)
        
        try:
            conn = sqlite3.connect(self.database_path)
            cursor = conn.cursor()
            cursor.execute("SELECT t.etiket_id, c.cihaz_adi || '.' || t.etiket_adi AS full_tag, t.modbus_tipi FROM etiketler t JOIN cihazlar c ON t.fk_cihaz_id = c.cihaz_id ORDER BY full_tag")
            all_tags_data = cursor.fetchall() # -> [(1, 'Motor_01.Sıcaklık', 'Holding Reg.'), ...]
            conn.close()
        except Exception as e:
            messagebox.showerror("Hata", f"Etiketler okunamadı: {e}", parent=add_alarm_win)
            add_alarm_win.destroy(); return
        
        if not all_tags_data:
            messagebox.showwarning("Etiket Yok", "Alarm tanımlayabilmek için önce bir etiket oluşturmalısınız.", parent=self.root)
            add_alarm_win.destroy(); return

        tag_display_list = [tag[1] for tag in all_tags_data]
        
        form_frame = ttk.Frame(add_alarm_win, padding="15"); form_frame.pack()
        ttk.Label(form_frame, text="İzlenecek Etiket:").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        tag_var = tk.StringVar(); 
        tag_combo = ttk.Combobox(form_frame, textvariable=tag_var, values=tag_display_list, state="readonly", width=30)
        tag_combo.grid(row=0, column=1, padx=5, pady=5, columnspan=2)
        
        ttk.Label(form_frame, text="Koşul:").grid(row=1, column=0, sticky="w", padx=5, pady=5)
        condition_var = tk.StringVar()
        condition_combo = ttk.Combobox(form_frame, textvariable=condition_var, state="readonly", width=5)
        condition_combo.grid(row=1, column=1, padx=5, pady=5, sticky="w")
        
        ttk.Label(form_frame, text="Tetikleme Değeri:").grid(row=2, column=0, sticky="w", padx=5, pady=5)
        value_var = tk.StringVar()
        # Değer için hem metin kutusu hem de seçim menüsü oluşturuyoruz, birini gizleyip diğerini göstereceğiz
        value_entry = ttk.Entry(form_frame, textvariable=value_var)
        value_combo = ttk.Combobox(form_frame, textvariable=value_var, values=['True', 'False'], state='readonly')

        def _on_alarm_tag_select(event=None):
                   """Etiket seçildiğinde formun geri kalanını dinamik olarak ayarlar."""
                   selected_tag_display = tag_var.get()
                   tag_type = ''
                   for tag_data in all_tags_data:
                       if tag_data[1] == selected_tag_display:
                           tag_type = tag_data[2]; break

                   if tag_type == 'Coil':
                       condition_combo['values'] = ['==', '!=']
                       condition_combo.set('==')
                       value_entry.grid_remove() # Metin kutusunu gizle
                       value_combo.grid(row=2, column=1, padx=5, pady=5, sticky="w")
                       value_combo.set('True')
                   else: # Holding Reg. veya Input Reg.
                       condition_combo['values'] = ['>', '<', '==', '!=']
                       condition_combo.set('>')
                       value_combo.grid_remove() # Seçim menüsünü gizle
                       value_entry.grid(row=2, column=1, padx=5, pady=5, columnspan=2, sticky="ew")

        tag_combo.bind('<<ComboboxSelected>>', _on_alarm_tag_select)
        ttk.Label(form_frame, text="Öncelik:").grid(row=3, column=0, sticky="w", padx=5, pady=5)
        priority_var = tk.StringVar(); priority_combo = ttk.Combobox(form_frame, textvariable=priority_var, values=["Yüksek", "Orta", "Düşük"], state="readonly", width=10); priority_combo.grid(row=3, column=1, padx=5, pady=5, sticky="w"); priority_combo.set("Orta")
        ttk.Label(form_frame, text="Alarm Mesajı:").grid(row=4, column=0, sticky="w", padx=5, pady=5)
        message_var = tk.StringVar(); ttk.Entry(form_frame, textvariable=message_var, width=32).grid(row=4, column=1, padx=5, pady=5, columnspan=2, sticky="ew")
        
        active_var = tk.IntVar(value=1); ttk.Checkbutton(form_frame, text="Bu kural aktif olsun", variable=active_var).grid(row=5, column=1, sticky="w", padx=5, pady=10)
        # İlk başta formu ilk etikete göre ayarla
        tag_combo.set(tag_display_list[0])
        _on_alarm_tag_select()

        def _save_new_rule():
            try:
                selected_tag_display = tag_var.get()
                if not selected_tag_display: messagebox.showerror("Eksik Bilgi", "Lütfen bir etiket seçin.", parent=add_alarm_win); return
                
                selected_tag_id = None
                for tag_id, display_name, tag_type in all_tags_data:
                    if display_name == selected_tag_display:
                        selected_tag_id = tag_id; break
                
                kosul = condition_var.get(); deger = value_var.get(); oncelik = priority_var.get(); mesaj = message_var.get(); aktif_mi = active_var.get()

                if not all([kosul, deger, oncelik]): messagebox.showerror("Eksik Bilgi", "Lütfen tüm gerekli alanları doldurun.", parent=add_alarm_win); return

                conn = sqlite3.connect(self.database_path)
                cursor = conn.cursor()
                cursor.execute("INSERT INTO alarm_kurallari (fk_etiket_id, kosul, tetikleme_degeri, oncelik, mesaj, aktif_mi) VALUES (?, ?, ?, ?, ?, ?)",
                               (selected_tag_id, kosul, deger, oncelik, mesaj, aktif_mi))
                conn.commit(); conn.close()
                self._load_alarm_rules_to_view()
                add_alarm_win.destroy()
            except Exception as e:
                messagebox.showerror("Hata", f"Alarm kuralı kaydedilemedi: {e}", parent=add_alarm_win)

        ttk.Button(form_frame, text="Kaydet", command=_save_new_rule).grid(row=6, column=1, sticky="e", pady=10, columnspan=2)
    
    def _edit_alarm_rule(self):
        """Seçili alarm kuralını düzenlemek için akıllı bir pop-up pencere açar."""
        selected_items = self.alarm_rules_tree.selection()
        if not selected_items:
            messagebox.showwarning("Seçim Yok", "Lütfen düzenlemek için bir alarm kuralı seçin."); return
        
        rule_id = self.alarm_rules_tree.item(selected_items[0])['values'][0]

        try:
            conn = sqlite3.connect(self.database_path)
            cursor = conn.cursor()
            cursor.execute("SELECT fk_etiket_id, kosul, tetikleme_degeri, oncelik, mesaj, aktif_mi FROM alarm_kurallari WHERE kural_id = ?", (rule_id,))
            rule_data = cursor.fetchone()
            if not rule_data:
                messagebox.showerror("Hata", "Kural veritabanında bulunamadı."); conn.close(); return
            
            cursor.execute("SELECT t.etiket_id, c.cihaz_adi || '.' || t.etiket_adi AS full_tag, t.modbus_tipi FROM etiketler t JOIN cihazlar c ON t.fk_cihaz_id = c.cihaz_id ORDER BY full_tag")
            all_tags_data = cursor.fetchall()
            conn.close()
        except Exception as e:
            messagebox.showerror("Hata", f"Kural verileri okunurken hata oluştu: {e}"); return

        fk_etiket_id, kosul, tetikleme_degeri, oncelik, mesaj, aktif_mi = rule_data
        
        edit_alarm_win = tk.Toplevel(self.root); edit_alarm_win.title("Alarm Kuralını Düzenle"); edit_alarm_win.transient(self.root); edit_alarm_win.resizable(False, False)
        
        tag_display_list = [tag[1] for tag in all_tags_data]
        current_tag_display = ""
        for tag_id, display_name, tag_type in all_tags_data:
            if tag_id == fk_etiket_id:
                current_tag_display = display_name; break

        form_frame = ttk.Frame(edit_alarm_win, padding="15"); form_frame.pack()
        ttk.Label(form_frame, text="İzlenecek Etiket:").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        tag_var = tk.StringVar(value=current_tag_display)
        tag_combo = ttk.Combobox(form_frame, textvariable=tag_var, values=tag_display_list, state="readonly", width=30); tag_combo.grid(row=0, column=1, padx=5, pady=5, columnspan=2)
        
        ttk.Label(form_frame, text="Koşul:").grid(row=1, column=0, sticky="w", padx=5, pady=5)
        condition_var = tk.StringVar(value=kosul)
        condition_combo = ttk.Combobox(form_frame, textvariable=condition_var, state="readonly", width=5); condition_combo.grid(row=1, column=1, padx=5, pady=5, sticky="w")
        
        ttk.Label(form_frame, text="Tetikleme Değeri:").grid(row=2, column=0, sticky="w", padx=5, pady=5)
        value_var = tk.StringVar(value=tetikleme_degeri)
        value_entry = ttk.Entry(form_frame, textvariable=value_var)
        value_combo = ttk.Combobox(form_frame, textvariable=value_var, values=['True', 'False'], state='readonly')
        
        def _on_alarm_tag_select(event=None):
            selected_tag_display = tag_var.get()
            tag_type = ''
            for tag_data in all_tags_data:
                if tag_data[1] == selected_tag_display:
                    tag_type = tag_data[2]; break
            
            if tag_type == 'Coil':
                condition_combo['values'] = ['==', '!=']
                if condition_var.get() not in ['==', '!=']: condition_var.set('==')
                value_entry.grid_remove()
                value_combo.grid(row=2, column=1, padx=5, pady=5, sticky="ew", columnspan=2)
            else: # Holding Reg. veya Input Reg.
                condition_combo['values'] = ['>', '<', '==', '!=']
                value_combo.grid_remove()
                value_entry.grid(row=2, column=1, padx=5, pady=5, columnspan=2, sticky="ew")

        tag_combo.bind('<<ComboboxSelected>>', _on_alarm_tag_select)
        
        ttk.Label(form_frame, text="Öncelik:").grid(row=3, column=0, sticky="w", padx=5, pady=5)
        priority_var = tk.StringVar(value=oncelik); priority_combo = ttk.Combobox(form_frame, textvariable=priority_var, values=["Yüksek", "Orta", "Düşük"], state="readonly", width=10); priority_combo.grid(row=3, column=1, padx=5, pady=5, sticky="w")
        ttk.Label(form_frame, text="Alarm Mesajı:").grid(row=4, column=0, sticky="w", padx=5, pady=5)
        message_var = tk.StringVar(value=mesaj); ttk.Entry(form_frame, textvariable=message_var, width=32).grid(row=4, column=1, padx=5, pady=5, columnspan=2, sticky="ew")
        active_var = tk.IntVar(value=aktif_mi); ttk.Checkbutton(form_frame, text="Bu kural aktif olsun", variable=active_var).grid(row=5, column=1, sticky="w", padx=5, pady=10)

        _on_alarm_tag_select() # Pencere açılırken formu doğru duruma getir

        def _update_rule():
                try:
                    selected_tag_display = tag_var.get()
                    selected_tag_id = None
                    for tag_id, display_name, tag_type in all_tags_data:
                        if display_name == selected_tag_display:
                            selected_tag_id = tag_id; break

                    new_kosul = condition_var.get(); new_deger = value_var.get(); new_oncelik = priority_var.get(); new_mesaj = message_var.get(); new_aktif_mi = active_var.get()
                    conn = sqlite3.connect(self.database_path)
                    cursor = conn.cursor()
                    cursor.execute("""UPDATE alarm_kurallari SET 
                                      fk_etiket_id = ?, kosul = ?, tetikleme_degeri = ?, 
                                      oncelik = ?, mesaj = ?, aktif_mi = ?
                                      WHERE kural_id = ?""",
                                   (selected_tag_id, new_kosul, new_deger, new_oncelik, new_mesaj, new_aktif_mi, rule_id))
                    conn.commit(); conn.close()
                    self._load_alarm_rules_to_view()
                    edit_alarm_win.destroy()
                except Exception as e:
                    messagebox.showerror("Hata", f"Alarm kuralı güncellenemedi: {e}", parent=edit_alarm_win)

        ttk.Button(form_frame, text="Kaydet", command=_update_rule).grid(row=6, column=1, sticky="e", pady=10, columnspan=2)

    def _delete_alarm_rule(self):
        """Seçili alarm kuralını veritabanından siler."""
        selected_items = self.alarm_rules_tree.selection()
        if not selected_items:
            messagebox.showwarning("Seçim Yok", "Lütfen silmek için bir alarm kuralı seçin."); return
        
        rule_id = self.alarm_rules_tree.item(selected_items[0])['values'][0]
        if messagebox.askyesno("Onay", f"ID'si {rule_id} olan alarm kuralını silmek istediğinizden emin misiniz?"):
            try:
                conn = sqlite3.connect(self.database_path)
                cursor = conn.cursor()
                cursor.execute("DELETE FROM alarm_kurallari WHERE kural_id = ?", (rule_id,))
                conn.commit(); conn.close()
                self._load_alarm_rules_to_view()
            except Exception as e:
                messagebox.showerror("Hata", f"Alarm kuralı silinemedi: {e}")

    def start_alarm_engine(self):
        """Arka planda çalışacak olan Alarm Motoru'nu başlatır."""
        if self.is_alarm_engine_active: return
        if not self.check_connection(): return

        self.is_alarm_engine_active = True
        self.alarm_engine_thread = threading.Thread(target=self._alarm_loop, daemon=True)
        self.alarm_engine_thread.start()
        print("Alarm Motoru başlatıldı.")

    def stop_alarm_engine(self):
        """Alarm Motoru'nu durdurur."""
        self.is_alarm_engine_active = False
        print("Alarm Motoru durduruldu.")
    
    def _alarm_loop(self):
        """
        Arka planda sürekli çalışarak alarm kurallarını kontrol eden ana döngü.
        """
        while self.is_alarm_engine_active:
            try:
                conn = sqlite3.connect(self.database_path)
                cursor = conn.cursor()
                # Sadece aktif olan kuralları ve gerekli tüm bilgileri çek
                sql = """SELECT r.kural_id, r.kosul, r.tetikleme_degeri, r.oncelik, r.mesaj, 
                                 t.modbus_adresi, t.modbus_tipi,
                                 c.cihaz_adi || '.' || t.etiket_adi AS full_tag_name
                         FROM alarm_kurallari r
                         JOIN etiketler t ON r.fk_etiket_id = t.etiket_id
                         JOIN cihazlar c ON t.fk_cihaz_id = c.cihaz_id
                         WHERE r.aktif_mi = 1"""
                cursor.execute(sql)
                rules_to_check = cursor.fetchall()
                conn.close()

                currently_active_alarms = {}

                for rule in rules_to_check:
                    kural_id, kosul, tetikleme_degeri, oncelik, mesaj, adres, tipi, full_tag_name = rule
                    
                    current_value = None
                    # Etiketin anlık değerini Modbus'tan oku
                    if tipi == 'Coil':
                        result = self.modbus_client.read_coils(address=adres, count=1)
                        if not result.isError(): current_value = result.bits[0]
                    elif tipi == 'Holding Reg.':
                        result = self.modbus_client.read_holding_registers(address=adres, count=1)
                        if not result.isError(): current_value = result.registers[0]
                    elif tipi == 'Input Reg.':
                        result = self.modbus_client.read_input_registers(address=adres, count=1)
                        if not result.isError(): current_value = result.registers[0]

                    if current_value is not None:
                        # Değerleri karşılaştırabilmek için tiplerini eşitle
                        try:
                            # Eğer sayısal bir karşılaştırma ise
                            trigger_val_numeric = float(tetikleme_degeri)
                            current_val_numeric = float(current_value)
                            expression = f"{current_val_numeric} {kosul} {trigger_val_numeric}"
                        except ValueError:
                            # Eğer metinsel (True/False) bir karşılaştırma ise
                            expression = f"'{str(current_value)}' {kosul} '{str(tetikleme_degeri)}'"
                        
                        # Karşılaştırmayı yap
                        if eval(expression):
                            # Alarm durumu oluştu!
                            alarm_data = {
                                "time": datetime.now().strftime('%H:%M:%S'),
                                "priority": oncelik,
                                "tag_name": full_tag_name,
                                "message": mesaj if mesaj else f"{full_tag_name} {kosul} {tetikleme_degeri}"
                            }
                            currently_active_alarms[kural_id] = alarm_data
                
                # Arayüzü ana thread üzerinden güvenle güncelle
                self.root.after(0, self._update_active_alarms_view, currently_active_alarms)

            except Exception as e:
                print(f"Alarm döngüsü hatası: {e}")
            
            time.sleep(2) # Kontrol aralığı (2 saniye)

    def _update_active_alarms_view(self, new_active_alarms):
        """Aktif alarmlar tablosunu en son duruma göre günceller ve satırları renklendirir/çevirir."""
        if not hasattr(self, 'active_alarms_tree') or not self.active_alarms_tree.winfo_exists():
            return

        # 1. Metinleri çevirmek için haritayı BURAYA DA EKLE (Hata buydu)
        priority_translation_map = {
            "Yüksek": self.strings.get("priority_high", "High"),
            "Orta": self.strings.get("priority_medium", "Medium"),
            "Düşük": self.strings.get("priority_low", "Low")
        }

        # 2. Renk stilini bulmak için harita (Anahtarlar sabit!)
        priority_tag_map = {
            "Yüksek": "Danger.Treeview",
            "Orta": "Warning.Treeview",
            "Düşük": "Info.Treeview"
        }

        if self.active_alarms != new_active_alarms:
            self.active_alarms = new_active_alarms
            for item in self.active_alarms_tree.get_children():
                self.active_alarms_tree.delete(item)

            for alarm_id, data in self.active_alarms.items():
                # Veritabanından gelen ham değeri al (örn: "Yüksek")
                raw_priority = data['priority']

                # Ekranda gösterilecek metni çevir
                display_priority = priority_translation_map.get(raw_priority, raw_priority)

                # Rengi belirlemek için stil etiketini bul
                tag_to_apply = (priority_tag_map.get(raw_priority),)

                self.active_alarms_tree.insert("", "end", iid=alarm_id, 
                                               values=(data['time'], display_priority, data['tag_name'], data['message']),
                                               tags=tag_to_apply)

        # ... (Fonksiyonun geri kalanı aynı) ...
        if self.active_alarms:
            highest_priority = "Düşük"
            for data in self.active_alarms.values():
                if data['priority'] == "Yüksek":
                    highest_priority = "Yüksek"
                    break
                if data['priority'] == "Orta":
                    highest_priority = "Orta"

            self.update_status(f"DİKKAT! {len(self.active_alarms)} ALARM AKTİF!", "error" if highest_priority == "Yüksek" else "info", is_persistent=True)
        else:
            if hasattr(self, 'persistent_status'):
                self.update_status(self.persistent_status[0], self.persistent_status[1], is_persistent=True)

    def open_tag_manager(self):
        """'Ekipman & Etiket Yöneticisi' menüsüne tıklandığında yeni bir pencere açar."""
        if hasattr(self, 'tag_win') and self.tag_win.winfo_exists():
            self.tag_win.lift(); return

        self.tag_win = tk.Toplevel(self.root)
        self.tag_win.title("Ekipman & Etiket Yöneticisi")
        self.tag_win.transient(self.root)
        self.tag_win.geometry("800x500")
        self.tag_win.protocol("WM_DELETE_WINDOW", self._on_tag_manager_close)

        main_pane = ttk.PanedWindow(self.tag_win, orient=tk.HORIZONTAL)
        main_pane.pack(fill="both", expand=True, padx=10, pady=10)
        
        cihaz_frame = ttk.Frame(main_pane, padding="5")
        etiket_frame = ttk.Frame(main_pane, padding="5")
        main_pane.add(cihaz_frame, weight=1)
        main_pane.add(etiket_frame, weight=3)

        cihaz_lf = ttk.LabelFrame(cihaz_frame, text="Ekipmanlar"); cihaz_lf.pack(fill="both", expand=True)
        cihaz_buttons_frame = ttk.Frame(cihaz_lf); cihaz_buttons_frame.pack(fill="x", pady=5)
        ttk.Button(cihaz_buttons_frame, text="Yeni Ekle", command=self._add_device).pack(side="left", padx=5)
        ttk.Button(cihaz_buttons_frame, text="Sil", command=self._delete_device).pack(side="left", padx=5)
        
        cihaz_list_frame = ttk.Frame(cihaz_lf); cihaz_list_frame.pack(fill="both", expand=True)
        cihaz_scrollbar = ttk.Scrollbar(cihaz_list_frame, orient="vertical")
        self.cihaz_listbox = tk.Listbox(cihaz_list_frame, yscrollcommand=cihaz_scrollbar.set, exportselection=False)
        cihaz_scrollbar.config(command=self.cihaz_listbox.yview); cihaz_scrollbar.pack(side="right", fill="y")
        self.cihaz_listbox.pack(side="left", fill="both", expand=True)
        self.cihaz_listbox.bind('<<ListboxSelect>>', self._on_device_select)

        self.etiket_lf = ttk.LabelFrame(etiket_frame, text="Etiketler", padding="10"); self.etiket_lf.pack(fill="both", expand=True)
        etiket_buttons_frame = ttk.Frame(self.etiket_lf); etiket_buttons_frame.pack(fill="x", pady=5)
        ttk.Button(etiket_buttons_frame, text="Yeni Ekle", command=self._add_tag).pack(side="left", padx=5)
        ttk.Button(etiket_buttons_frame, text="Sil", command=self._delete_tag).pack(side="left", padx=5)
        
        etiket_columns = ("id", "address", "type", "tag_name")
        self.etiket_tree = ttk.Treeview(self.etiket_lf, columns=etiket_columns, show="headings")
        self.etiket_tree.heading("id", text="ID"); self.etiket_tree.heading("address", text="Adres"); self.etiket_tree.heading("type", text="Tip"); self.etiket_tree.heading("tag_name", text="Etiket Adı")
        self.etiket_tree.column("id", width=40, anchor='center'); self.etiket_tree.column("address", width=60, anchor='center'); self.etiket_tree.column("type", width=100)
        self.etiket_tree.pack(fill="both", expand=True, pady=5)

        self._load_devices_to_listbox()

    def _on_tag_manager_close(self):
        """Etiket yöneticisi kapatıldığında etiket önbelleğini yeniler."""
        self._refresh_caches_and_ui()
        self.tag_win.destroy()

    def _refresh_caches_and_ui(self):
        """Önbelleği ve ilgili tüm arayüz bileşenlerini yeniler."""
        self._load_tags_into_cache()
        self._populate_device_combobox()
        self._on_device_combo_select()

    def _load_devices_to_listbox(self):
        try:
            self.cihaz_listbox.delete(0, tk.END)
            conn = sqlite3.connect(self.database_path)
            cursor = conn.cursor()
            cursor.execute("SELECT cihaz_adi FROM cihazlar ORDER BY cihaz_adi")
            devices = cursor.fetchall()
            for device in devices:
                self.cihaz_listbox.insert(tk.END, device[0])
            conn.close()
            self._on_device_select()
        except Exception as e:
            messagebox.showerror("Hata", f"Cihazlar yüklenemedi: {e}", parent=self.tag_win)

    def _on_device_select(self, event=None):
        selected_indices = self.cihaz_listbox.curselection()
        if not selected_indices:
            self.etiket_lf.config(text="Etiketler")
            for item in self.etiket_tree.get_children(): self.etiket_tree.delete(item)
            return
        
        selected_device_name = self.cihaz_listbox.get(selected_indices[0])
        self.etiket_lf.config(text=f"'{selected_device_name}' Ekipmanına Ait Etiketler")
        for item in self.etiket_tree.get_children(): self.etiket_tree.delete(item)
        try:
            conn = sqlite3.connect(self.database_path)
            cursor = conn.cursor()
            sql = """SELECT e.etiket_id, e.modbus_adresi, e.modbus_tipi, e.etiket_adi 
                     FROM etiketler e JOIN cihazlar c ON e.fk_cihaz_id = c.cihaz_id 
                     WHERE c.cihaz_adi = ? ORDER BY e.modbus_adresi"""
            cursor.execute(sql, (selected_device_name,))
            tags = cursor.fetchall()
            for tag in tags:
                self.etiket_tree.insert("", "end", values=tag)
            conn.close()
        except Exception as e:
            messagebox.showerror("Hata", f"Etiketler yüklenemedi: {e}", parent=self.tag_win)

    def _add_device(self):
        device_name = simpledialog.askstring("Yeni Ekipman", "Lütfen yeni ekipmanın adını girin:", parent=self.root)
        if device_name:
            try:
                conn = sqlite3.connect(self.database_path)
                cursor = conn.cursor()
                cursor.execute("INSERT INTO cihazlar (cihaz_adi) VALUES (?)", (device_name,))
                conn.commit(); conn.close()
                self._load_devices_to_listbox()
                self._refresh_caches_and_ui()
            except sqlite3.IntegrityError:
                messagebox.showerror("Hata", "Bu isimde bir ekipman zaten mevcut.", parent=self.root)
            except Exception as e:
                messagebox.showerror("Hata", f"Ekipman eklenemedi: {e}", parent=self.root)


    def _delete_device(self):
        selected_indices = self.cihaz_listbox.curselection()
        if not selected_indices: messagebox.showwarning("Seçim Yok", "Lütfen silmek için bir ekipman seçin."); return
        
        device_name = self.cihaz_listbox.get(selected_indices[0])
        if messagebox.askyesno("Onay", f"'{device_name}' ekipmanını ve ona ait TÜM etiketleri silmek istediğinizden emin misiniz?"):
            try:
                conn = sqlite3.connect(self.database_path)
                cursor = conn.cursor()
                cursor.execute("DELETE FROM cihazlar WHERE cihaz_adi = ?", (device_name,))
                conn.commit(); conn.close()
                self._load_devices_to_listbox()
                self._refresh_caches_and_ui()
            except Exception as e:
                messagebox.showerror("Hata", f"Ekipman silinemedi: {e}", parent=self.root)

    def _add_tag(self):
        selected_indices = self.cihaz_listbox.curselection()
        if not selected_indices: messagebox.showwarning("Seçim Yok", "Lütfen etiket eklemek için önce bir ekipman seçin."); return
        
        add_tag_win = tk.Toplevel(self.root); add_tag_win.title("Yeni Etiket Ekle"); add_tag_win.transient(self.root)
        form_frame = ttk.Frame(add_tag_win, padding="10"); form_frame.pack()
        ttk.Label(form_frame, text="Etiket Adı:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        tag_name_var = tk.StringVar(); ttk.Entry(form_frame, textvariable=tag_name_var).grid(row=0, column=1, padx=5, pady=5)
        ttk.Label(form_frame, text="Modbus Tipi:").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        tag_type_var = tk.StringVar()
        tag_type_combo = ttk.Combobox(form_frame, textvariable=tag_type_var, values=["Holding Reg.", "Input Reg.", "Coil"], state="readonly")
        tag_type_combo.grid(row=1, column=1, padx=5, pady=5); tag_type_combo.set("Holding Reg.")
        ttk.Label(form_frame, text="Modbus Adresi:").grid(row=2, column=0, padx=5, pady=5, sticky="w")
        tag_addr_var = tk.IntVar(); ttk.Entry(form_frame, textvariable=tag_addr_var, width=10).grid(row=2, column=1, padx=5, pady=5)
        
        def _save_new_tag():
            try:
                device_name = self.cihaz_listbox.get(selected_indices[0])
                tag_name = tag_name_var.get(); tag_type = tag_type_var.get(); tag_addr = tag_addr_var.get()
                if not all([tag_name, tag_type]): messagebox.showerror("Eksik Bilgi", "Lütfen tüm alanları doldurun.", parent=add_tag_win); return
                
                conn = sqlite3.connect(self.database_path); cursor = conn.cursor()
                cursor.execute("SELECT etiket_adi FROM etiketler WHERE modbus_tipi = ? AND modbus_adresi = ?", (tag_type, tag_addr))
                existing_tag = cursor.fetchone()
                if existing_tag:
                    messagebox.showerror("Hata", f"Bu adres ({tag_type} - {tag_addr}) zaten '{existing_tag[0]}' etiketi için kullanılıyor.", parent=add_tag_win)
                    conn.close(); return
                
                cursor.execute("SELECT cihaz_id FROM cihazlar WHERE cihaz_adi = ?", (device_name,))
                cihaz_id_result = cursor.fetchone()
                if cihaz_id_result:
                    cihaz_id = cihaz_id_result[0]
                    cursor.execute("INSERT INTO etiketler (fk_cihaz_id, modbus_adresi, modbus_tipi, etiket_adi) VALUES (?, ?, ?, ?)", (cihaz_id, tag_addr, tag_type, tag_name))
                    conn.commit()
                conn.close()
                self._on_device_select()
                self._refresh_caches_and_ui()
                add_tag_win.destroy()
            except Exception as e:
                messagebox.showerror("Hata", f"Etiket kaydedilemedi: {e}", parent=add_tag_win)
        
        ttk.Button(form_frame, text="Kaydet", command=_save_new_tag).grid(row=3, column=1, pady=10)

    def _delete_tag(self):
        selected_items = self.etiket_tree.selection()
        if not selected_items: messagebox.showwarning("Seçim Yok", "Lütfen silmek için bir etiket seçin."); return
        tag_id = self.etiket_tree.item(selected_items[0])['values'][0]
        if messagebox.askyesno("Onay", f"ID'si {tag_id} olan etiketi silmek istediğinizden emin misiniz?"):
            try:
                conn = sqlite3.connect(self.database_path); cursor = conn.cursor()
                cursor.execute("DELETE FROM etiketler WHERE etiket_id = ?", (tag_id,))
                conn.commit(); conn.close()
                self._on_device_select()
                self._refresh_caches_and_ui()
            except Exception as e:
                messagebox.showerror("Hata", f"Etiket silinemedi: {e}")


    def open_settings_window(self):
        if hasattr(self, 'settings_win') and self.settings_win.winfo_exists(): self.settings_win.lift(); return
        self.settings_win = tk.Toplevel(self.root)
        self.settings_win.title(self.strings.get('settings_window_title'))
        self.settings_win.transient(self.root)
        main_frame = ttk.Frame(self.settings_win, padding="20"); main_frame.pack(fill="both", expand=True)
        server_frame = ttk.LabelFrame(main_frame, text=self.strings.get('settings_server_frame'), padding="10"); server_frame.pack(fill="x", pady=10)
        ttk.Label(server_frame, text=self.strings.get('settings_ip_label')).grid(row=0, column=0, sticky="w", padx=5, pady=5)
        ip_var = tk.StringVar(value=self.server_ip); ip_entry = ttk.Entry(server_frame, textvariable=ip_var); ip_entry.grid(row=0, column=1, padx=5, pady=5)
        ttk.Label(server_frame, text=self.strings.get('settings_port_label')).grid(row=1, column=0, sticky="w", padx=5, pady=5)
        port_var = tk.StringVar(value=self.server_port); port_entry = ttk.Entry(server_frame, textvariable=port_var); port_entry.grid(row=1, column=1, padx=5, pady=5)
        appearance_frame = ttk.LabelFrame(main_frame, text=self.strings.get('settings_appearance_frame'), padding="10"); appearance_frame.pack(fill="x", pady=10)
        ttk.Label(appearance_frame, text=self.strings.get('settings_lang_label')).grid(row=0, column=0, sticky="w", padx=5, pady=5)
        lang_var = tk.StringVar(value=self.language); lang_combo = ttk.Combobox(appearance_frame, textvariable=lang_var, values=["tr", "en"], state="readonly"); lang_combo.grid(row=0, column=1, padx=5, pady=5)
        ttk.Label(appearance_frame, text=self.strings.get('settings_theme_label')).grid(row=1, column=0, sticky="w", padx=5, pady=5)
        theme_var = tk.StringVar(value=self.theme); theme_combo = ttk.Combobox(appearance_frame, textvariable=theme_var, values=["light", "dark"], state="readonly"); theme_combo.grid(row=1, column=1, padx=5, pady=5)
        button_frame = ttk.Frame(main_frame); button_frame.pack(fill="x", pady=20)
        def _save_settings():
            old_lang = self.language
            self.config.set('Connection', 'ip', ip_var.get()); self.config.set('Connection', 'port', port_var.get())
            self.config.set('Appearance', 'theme', theme_var.get()); self.config.set('Appearance', 'language', lang_var.get())
            with open('config.ini', 'w') as configfile: self.config.write(configfile)
            self.load_config()
            self._apply_theme() # <-- STİLLER SIFIRLANIYOR
            self._update_styles() # <-- EKLENECEK SATIR: ÖZEL RENKLER YENİDEN UYGULANIYOR
            self._configure_treeview_tags()
            if old_lang != self.language:
                self._load_language()
                self._create_menubar() 
                self._update_all_ui_text() 
            self.update_status(self.persistent_status[0], self.persistent_status[1], is_persistent=True)
            messagebox.showinfo("Başarılı", "Ayarlar kaydedildi.", parent=self.settings_win)
            self.settings_win.destroy()
        ttk.Button(button_frame, text=self.strings.get('settings_save_button'), command=_save_settings).pack(side="right", padx=5)
        ttk.Button(button_frame, text=self.strings.get('settings_cancel_button'), command=self.settings_win.destroy).pack(side="right", padx=5)

    def _init_database(self):
        try:
            db_folder = os.path.dirname(self.database_path)
            if db_folder and not os.path.exists(db_folder): os.makedirs(db_folder)
            if not os.path.exists(self.database_path): print(f"DB not found, creating new: {self.database_path}")
            conn = sqlite3.connect(self.database_path); cursor = conn.cursor()
            cursor.execute('''CREATE TABLE IF NOT EXISTS sensor_data (id INTEGER PRIMARY KEY, timestamp TEXT, register_type TEXT, register_address INTEGER, register_value TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS cihazlar (cihaz_id INTEGER PRIMARY KEY, cihaz_adi TEXT NOT NULL UNIQUE, aciklama TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS etiketler (etiket_id INTEGER PRIMARY KEY, fk_cihaz_id INTEGER NOT NULL, modbus_adresi INTEGER NOT NULL, modbus_tipi TEXT NOT NULL, etiket_adi TEXT NOT NULL, FOREIGN KEY (fk_cihaz_id) REFERENCES cihazlar (cihaz_id) ON DELETE CASCADE, UNIQUE(modbus_tipi, modbus_adresi))''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS alarm_kurallari (kural_id INTEGER PRIMARY KEY, fk_etiket_id INTEGER NOT NULL, kosul TEXT NOT NULL, tetikleme_degeri TEXT NOT NULL, oncelik TEXT NOT NULL, mesaj TEXT, aktif_mi INTEGER NOT NULL, FOREIGN KEY (fk_etiket_id) REFERENCES etiketler (etiket_id) ON DELETE CASCADE)''')
            conn.commit(); conn.close()
        except Exception as e: messagebox.showerror("Veritabanı Hatası", f"Veritabanı oluşturulamadı: {e}")

    def _on_closing(self):
        """Uygulama kapanırken tüm thread'leri güvenli şekilde durdurur."""
        try:
            # Önce alarm motorunu durdur
            self.stop_alarm_engine()

            # Logging'i durdur
            if self.is_logging_active:
                self.stop_logging()
                # Logging thread'inin bitmesini bekle
                if self.logging_thread and self.logging_thread.is_alive():
                    self.logging_thread.join(timeout=2)

            # Scanning'i durdur
            if self.is_scanning_active:
                self.is_scanning_active = False
                if self.scanning_thread and self.scanning_thread.is_alive():
                    self.scanning_thread.join(timeout=2)

            # Modbus bağlantısını kapat
            if self.modbus_client and self.modbus_client.is_socket_open():
                self.modbus_client.close()

            # Config'i kaydet
            try:
                with open('config.ini', 'w') as configfile:
                    self.config.write(configfile)
            except Exception as config_error:
                print(f"Config kaydetme hatası: {config_error}")

        except Exception as e:
            print(f"Kapatma sırasında hata: {e}")
        finally:
            # Her durumda pencereyi kapat
            self.root.destroy()

    def show_about_dialog(self):
        messagebox.showinfo(self.strings.get('menu_help_about'), self.strings.get('about_content') + self.config.get('User', 'name', fallback=''))

    def show_help_dialog(self):
        messagebox.showinfo(self.strings.get('menu_help_usage'), self.strings.get('help_usage_content'))


    def _new_database(self):
        if self.is_logging_active: messagebox.showwarning("Uyarı", "Lütfen önce veri kaydını durdurun."); return
        filepath = filedialog.asksaveasfilename(initialdir=".", title="Yeni Kayıt Dosyası Oluştur", defaultextension=".db", filetypes=[("SQLite Veritabanı", "*.db")])
        if filepath: self.database_path = filepath; self.config.set('Database', 'last_opened', self.database_path); self._init_database(); self._load_tags_into_cache(); self.update_status(f"Yeni veritabanı: {filepath.split('/')[-1]}", "info")
    
    def _open_database(self):
        if self.is_logging_active: messagebox.showwarning("Uyarı", "Lütfen önce veri kaydını durdurun."); return
        filepath = filedialog.askopenfilename(initialdir=".", title="Kayıt Dosyası Aç", filetypes=[("SQLite Veritabanı", "*.db")])
        if filepath: self.database_path = filepath; self.config.set('Database', 'last_opened', self.database_path); self._load_tags_into_cache(); self.update_status(f"Veritabanı açıldı: {filepath.split('/')[-1]}", "info")

    def export_to_csv(self):
        if self.is_logging_active: messagebox.showwarning("Uyarı", "Lütfen önce veri kaydını durdurun."); return
        save_path = filedialog.asksaveasfilename(initialdir=".", title="Kayıtları CSV Olarak Dışa Aktar", defaultextension=".csv", filetypes=[("CSV Dosyası", "*.csv")])
        if not save_path: return
        try:
            conn = sqlite3.connect(self.database_path); cursor = conn.cursor(); cursor.execute("SELECT * FROM sensor_data"); rows = cursor.fetchall()
            if not rows: messagebox.showinfo("Bilgi", "Dışa aktarılacak veri bulunamadı."); conn.close(); return
            with open(save_path, 'w', newline='', encoding='utf-8') as f: writer = csv.writer(f); writer.writerow([d[0] for d in cursor.description]); writer.writerows(rows)
            conn.close(); messagebox.showinfo("Başarılı", f"Kayıtlar başarıyla '{save_path.split('/')[-1]}' dosyasına aktarıldı.")
        except Exception as e: messagebox.showerror("Dışa Aktarma Hatası", f"Bir hata oluştu: {e}")

    def update_status(self, message, status_type='normal', is_persistent=False):
        """Durum çubuğunu, yeni palet sistemine göre istenen mesaj ve renkle günceller."""
        if self.status_revert_id:
            self.root.after_cancel(self.status_revert_id)
            self.status_revert_id = None
            
        if hasattr(self, 'status_label'):
            status_prefix = self.strings.get('status_prefix', 'Durum')
            
            # --- DÜZELTME BAŞLANGICI: Yeni palet sistemini kullan ---
            palette = self.palettes[self.theme]
            
            # Eski status_type isimlerini yeni palet anahtarlarına eşle
            color_key_map = {
                'success': 'success',
                'error': 'danger',
                'info': 'info_accent',
                'normal': 'text_main'
            }
            # Haritadan doğru renk anahtarını al, bulamazsan varsayılan metin rengini kullan
            color_key = color_key_map.get(status_type, 'text_main')
            color = palette[color_key]
            # --- DÜZELTME SONU ---

            self.status_label.config(text=f"{status_prefix}: {message}", foreground=color)
            self.last_status = (message, status_type)
            
            if is_persistent:
                self.persistent_status = (message, status_type)
            else:
                self.status_revert_id = self.root.after(5000, self._revert_status_to_default)


    def _revert_status_to_default(self):
        """Durum çubuğunu en son kalıcı duruma geri döndürür."""
        self.status_revert_id = None
        # Sadece son durum mesajı, mevcut kalıcı durumdan farklıysa güncelle
        if self.last_status != self.persistent_status:
            self.update_status(self.persistent_status[0], self.persistent_status[1], is_persistent=True)


    def check_connection(self):
        """Herhangi bir Modbus işlemi yapmadan önce bağlantıyı kontrol eder."""
        if not self.modbus_client or not self.modbus_client.is_socket_open():
            messagebox.showwarning(self.strings.get('no_connection_title', "Bağlantı Yok"), self.strings.get('no_connection_msg', "Lütfen önce sunucuya bağlanın."))
            return False
        return True

    def connect_to_server(self):
        self.load_config()
        self.modbus_client = ModbusTcpClient(self.server_ip, port=self.server_port)
        if self.modbus_client.connect():
            self.update_status(self.strings.get("status_connected", "Bağlantı Kuruldu."), "success", is_persistent=True)
            self.root.after(200, lambda: self._update_live_view('holding'))
            self.start_alarm_engine()
        else:
            self.update_status(self.strings.get("status_connect_fail", "Bağlantı Başarısız!"), "error", is_persistent=True)


    def disconnect_from_server(self):
        self.stop_alarm_engine()
        if self.modbus_client and self.modbus_client.is_socket_open():
            self.modbus_client.close()
            self.update_status(self.strings.get("status_disconnected", "Bağlantı Kapatıldı."), "error", is_persistent=True)
        else:
            self.update_status(self.strings.get("status_not_connected", "Zaten bir bağlantı yok."), "info")
        
        # Thread'in bitmesini bekle
        if self.alarm_engine_thread and self.alarm_engine_thread.is_alive():
            self.alarm_engine_thread.join(timeout=3)
        
        # Eğer arayüz hala varsa, aktif alarmlar tablosunu temizle
        try:
            if hasattr(self, 'active_alarms_tree') and self.active_alarms_tree.winfo_exists():
                # Arayüzü ana thread'den güvenli bir şekilde güncellemek için 'after' kullan
                self.root.after(0, self._update_active_alarms_view, {})
        except Exception as e:
            print(f"Alarm tablosu temizleme hatası: {e}")
    
        print("Alarm Motoru durduruldu.")

    def _alarm_loop(self):
        """
        Arka planda sürekli çalışarak alarm kurallarını kontrol eden ana döngü.
        """
        while self.is_alarm_engine_active:
            conn = None
            try:
                # Modbus bağlantı kontrolü
                if not self.modbus_client or not self.modbus_client.is_socket_open():
                    time.sleep(2)
                    continue

                # Thread-safe veritabanı bağlantısı
                conn = sqlite3.connect(self.database_path, check_same_thread=False)
                cursor = conn.cursor()

                # Sadece aktif olan kuralları ve gerekli tüm bilgileri çek
                sql = """SELECT r.kural_id, r.kosul, r.tetikleme_degeri, r.oncelik, r.mesaj, 
                                 t.modbus_adresi, t.modbus_tipi,
                                 c.cihaz_adi || '.' || t.etiket_adi AS full_tag_name
                         FROM alarm_kurallari r
                         JOIN etiketler t ON r.fk_etiket_id = t.etiket_id
                         JOIN cihazlar c ON t.fk_cihaz_id = c.cihaz_id
                         WHERE r.aktif_mi = 1"""
                cursor.execute(sql)
                rules_to_check = cursor.fetchall()
                conn.close()
                conn = None

                currently_active_alarms = {}

                for rule in rules_to_check:
                    kural_id, kosul, tetikleme_degeri, oncelik, mesaj, adres, tipi, full_tag_name = rule

                    current_value = None
                    # Etiketin anlık değerini Modbus'tan oku
                    try:
                        if tipi == 'Coil':
                            result = self.modbus_client.read_coils(address=adres, count=1)
                            if not result.isError():
                                current_value = result.bits[0]
                        elif tipi == 'Holding Reg.':
                            result = self.modbus_client.read_holding_registers(address=adres, count=1)
                            if not result.isError():
                                current_value = result.registers[0]
                        elif tipi == 'Input Reg.':
                            result = self.modbus_client.read_input_registers(address=adres, count=1)
                            if not result.isError():
                                current_value = result.registers[0]
                    except Exception as modbus_error:
                        print(f"Modbus okuma hatası (Adres {adres}): {modbus_error}")
                        continue

                    if current_value is not None:
                        # Güvenli karşılaştırma yap
                        if self._compare_alarm_condition(current_value, kosul, tetikleme_degeri):
                            # Alarm durumu oluştu!
                            alarm_data = {
                                "time": datetime.now().strftime('%H:%M:%S'),
                                "priority": oncelik,
                                "tag_name": full_tag_name,
                                "message": mesaj if mesaj else f"{full_tag_name} {kosul} {tetikleme_degeri}"
                            }
                            currently_active_alarms[kural_id] = alarm_data

                # Arayüzü ana thread üzerinden güvenle güncelle
                if hasattr(self, 'root') and self.root.winfo_exists():
                    self.root.after(0, self._update_active_alarms_view, currently_active_alarms)

            except Exception as e:
                print(f"Alarm döngüsü hatası: {e}")
            finally:
                if conn:
                    try:
                        conn.close()
                    except:
                        pass
                    
            time.sleep(2)  # Kontrol aralığı (2 saniye)

    def _compare_alarm_condition(self, current_value, operator, target_value):
        """Alarm koşullarını güvenli şekilde karşılaştırır."""
        try:
            if operator == '>':
                return float(current_value) > float(target_value)
            elif operator == '<':
                return float(current_value) < float(target_value)
            elif operator == '==':
                # String karşılaştırması için
                if isinstance(current_value, bool) or target_value.lower() in ['true', 'false']:
                    return str(current_value).upper() == str(target_value).upper()
                else:
                    return float(current_value) == float(target_value)
            elif operator == '!=':
                if isinstance(current_value, bool) or target_value.lower() in ['true', 'false']:
                    return str(current_value).upper() != str(target_value).upper()
                else:
                    return float(current_value) != float(target_value)
        except (ValueError, TypeError) as e:
            print(f"Karşılaştırma hatası: {current_value} {operator} {target_value} -> {e}")
            return False
        return False
            
    def _update_active_alarms_view(self, new_active_alarms):
        """Aktif alarmlar tablosunu en son duruma göre günceller."""
        if not hasattr(self, 'active_alarms_tree'): return

        if self.active_alarms != new_active_alarms:
            self.active_alarms = new_active_alarms
            for item in self.active_alarms_tree.get_children():
                self.active_alarms_tree.delete(item)
            for alarm_id, data in self.active_alarms.items():
                self.active_alarms_tree.insert("", "end", iid=alarm_id, values=(data['time'], data['priority'], data['tag_name'], data['message']))

        if self.active_alarms:
            highest_priority = "Düşük"
            for data in self.active_alarms.values():
                if data['priority'] == "Yüksek": highest_priority = "Yüksek"; break
                if data['priority'] == "Orta": highest_priority = "Orta"

            self.update_status(f"DİKKAT! {len(self.active_alarms)} ALARM AKTİF!", "error" if highest_priority == "Yüksek" else "info", is_persistent=True)
        else:
            # Aktif alarm yoksa, durumu normale (bağlantı durumuna) döndür
            self.update_status(self.persistent_status[0], self.persistent_status[1], is_persistent=True)

    def read_holding_register(self): 
        if not self.check_connection(): return
        try:
            addr = int(self.reg_addr_entry.get())
            result = self.modbus_client.read_holding_registers(address=addr, count=1)
            if not result.isError():
                value = result.registers[0]
                self.reg_val_entry.delete(0, tk.END)
                self.reg_val_entry.insert(0, str(value))
                self.reg_read_val_label.config(text=f"Okunan Değer: < {value} >")
                self.update_status(f"Adres {addr} okundu.", "normal")
            else:
                messagebox.showerror("Hata", "Register okunamadı.")
        except Exception as e:
            messagebox.showerror("Hata", f"Geçersiz giriş veya hata: {e}")

    def write_holding_register(self):
        if not self.check_connection(): return
        try:
            addr = int(self.reg_addr_entry.get())
            val = int(self.reg_val_entry.get())
            result = self.modbus_client.write_register(addr, val)
            if not result.isError():
                self.update_status(f"Adres {addr}'e {val} değeri yazıldı.", "success")
                self.reg_read_val_label.config(text="Okunan Değer: < - >")
            else:
                messagebox.showerror("Hata", "Register yazılamadı.")
        except Exception as e:
            messagebox.showerror("Hata", f"Geçersiz giriş veya hata: {e}")

    def read_coil(self):
        if not self.check_connection(): return
        try:
            addr = int(self.coil_addr_entry.get())
            result = self.modbus_client.read_coils(address=addr, count=1)
            if not result.isError():
                status = result.bits[0]
                self.coil_read_val_label.config(text=f"Okunan Durum: < {status} >")
                self.update_status(f"Adres {addr} (Coil) okundu.", "normal")
            else:
                messagebox.showerror("Hata", "Coil okunamadı.")
        except Exception as e:
            messagebox.showerror("Hata", f"Geçersiz giriş veya hata: {e}")

    def write_coil(self):
        if not self.check_connection(): return
        try:
            addr = int(self.coil_addr_entry.get())
            val_str = self.coil_val_combo.get()
            val = True if val_str == "True" else False
            result = self.modbus_client.write_coil(addr, val)
            if not result.isError():
                self.update_status(f"Adres {addr} (Coil) durumuna {val} yazıldı.", "success")
                self.coil_read_val_label.config(text="Okunan Durum: < - >")
            else:
                messagebox.showerror("Hata", "Coil yazılamadı.")
        except Exception as e:
            messagebox.showerror("Hata", f"Geçersiz giriş veya hata: {e}")


    def _update_live_view(self, view_type):
        """Canlı veri tablosunu günceller ve alarm durumundaki satırları renklendirir."""
        if not self.check_connection(): return
        if not hasattr(self, 'live_tree') or not self.live_tree.winfo_exists(): return

        self.current_live_view = view_type
        try:
            # --- Alarm durumundaki etiketleri ve önceliklerini hızlıca aramak için hazırla ---
            alarmed_tags_info = {data['tag_name']: data['priority'] for data in self.active_alarms.values()}
            priority_tag_map = {
                self.strings.get("priority_high", "Yüksek"): "Danger.Treeview",
                self.strings.get("priority_medium", "Medium"): "Warning.Treeview",
                self.strings.get("priority_low", "Low"): "Info.Treeview"
            }

            for item in self.live_tree.get_children():
                self.live_tree.delete(item)
            
            count = 50 
            if view_type == 'coil':
                self.live_tree.heading("deger", text=self.strings.get('tab2_header_status', "Durum"))
                result = self.modbus_client.read_coils(address=0, count=count)
                if not result.isError():
                    for i, val in enumerate(result.bits[:count]):
                        tag_info = self.tag_cache.get(("Coil", i), {}); cihaz = tag_info.get('cihaz_adi', ''); etiket = tag_info.get('etiket_adi', '')
                        
                        # --- Bu etiket alarmda mı diye kontrol et ve renklendir ---
                        full_tag_name = f"{cihaz}.{etiket}" if cihaz and etiket else ""
                        tag_to_apply = ()
                        if full_tag_name in alarmed_tags_info:
                            priority = alarmed_tags_info[full_tag_name]
                            tag_to_apply = (priority_tag_map.get(priority),)

                        self.live_tree.insert("", "end", values=(cihaz, etiket, i, str(val)), tags=tag_to_apply)
                else:
                    print(f"Coil okuma hatası: {result}")
            else:
                self.live_tree.heading("deger", text=self.strings.get('tab2_header_value', "Değer"))
                reg_type_str = "Holding Reg." if view_type == 'holding' else "Input Reg."
                read_func = self.modbus_client.read_holding_registers if view_type == 'holding' else self.modbus_client.read_input_registers
                result = read_func(address=0, count=count)
                if not result.isError():
                    for i, val in enumerate(result.registers):
                        tag_info = self.tag_cache.get((reg_type_str, i), {}); cihaz = tag_info.get('cihaz_adi', ''); etiket = tag_info.get('etiket_adi', '')
                        
                        # --- Bu etiket alarmda mı diye kontrol et ve renklendir ---
                        full_tag_name = f"{cihaz}.{etiket}" if cihaz and etiket else ""
                        tag_to_apply = ()
                        if full_tag_name in alarmed_tags_info:
                            priority = alarmed_tags_info[full_tag_name]
                            tag_to_apply = (priority_tag_map.get(priority),)

                        self.live_tree.insert("", "end", values=(cihaz, etiket, i, val), tags=tag_to_apply)
                else:
                    print(f"Register okuma hatası: {result}")
            
            message = self.strings.get("status_view_updated", "'{view}' view updated.").format(view=view_type)
            self.update_status(message, "normal")

        except Exception as e:
            print(f"Live view güncelleme hatası: {e}")
            self.update_status(f"Görünüm güncellenirken hata: {str(e)}", "error")

    def _periodic_live_view_update(self):
        try:
            if hasattr(self, 'notebook') and self.notebook.winfo_exists() and self.notebook.index(self.notebook.select()) == 1:
                if self.modbus_client and self.modbus_client.is_socket_open(): self._update_live_view(self.current_live_view)
        except Exception: pass
        finally: self.root.after(2000, self._periodic_live_view_update)


    def start_logging(self):
        if self.is_logging_active: messagebox.showinfo("Bilgi", "Veri kaydı zaten aktif."); return
        if not self.check_connection(): return
        try:
            self.log_addr = int(self.log_addr_entry.get()); self.log_count = int(self.log_count_entry.get())
            self.log_interval = int(self.log_interval_entry.get()); self.log_type = self.log_type_combo.get()
            self.is_logging_active = True
            self.start_log_button.config(state="disabled"); self.stop_log_button.config(state="normal")
            self.logging_thread = threading.Thread(target=self._logging_loop, daemon=True)
            self.logging_thread.start()
            self.update_status(f"Adres {self.log_addr}'den başlayarak {self.log_count} adet {self.log_type} kaydı başladı.", "info")
        except ValueError: messagebox.showerror("Giriş Hatası", "Lütfen kayıt ayarları için geçerli sayılar girin.")

    def stop_logging(self):
        self.is_logging_active = False
        self.start_log_button.config(state="normal"); self.stop_log_button.config(state="disabled")
        self.update_status("Veri kaydı durduruldu.", "normal")

    def _logging_loop(self):
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        while self.is_logging_active:
            try:
                current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S'); data_to_insert = []
                read_func, result_key, type_str = None, None, self.log_type
                if self.log_type == "Coil": read_func, result_key = self.modbus_client.read_coils, 'bits'
                elif self.log_type == "Holding Reg.": read_func, result_key = self.modbus_client.read_holding_registers, 'registers'
                elif self.log_type == "Input Reg.": read_func, result_key = self.modbus_client.read_input_registers, 'registers'
                if read_func:
                    result = read_func(address=self.log_addr, count=self.log_count)
                    if not result.isError():
                        values = getattr(result, result_key)
                        for i, val in enumerate(values[:self.log_count]): data_to_insert.append((current_time, type_str, self.log_addr + i, str(val)))
                if data_to_insert:
                    sql = "INSERT INTO sensor_data (timestamp, register_type, register_address, register_value) VALUES (?, ?, ?, ?)"
                    cursor.executemany(sql, data_to_insert)
                    conn.commit()
                    print(f"Logged {len(data_to_insert)} records at {current_time}")
                time.sleep(self.log_interval)
            except Exception as e: print(f"Logging hatası: {e}"); time.sleep(self.log_interval)
        conn.close()
        
    def start_scanning(self):
        if self.is_scanning_active: messagebox.showinfo("Bilgi", "Tarama zaten devam ediyor."); return
        if not self.check_connection(): return
        try:
            start_addr = int(self.scan_start_addr_entry.get()); end_addr = int(self.scan_end_addr_entry.get())
            if start_addr > end_addr: messagebox.showerror("Giriş Hatası", "Başlangıç adresi, bitiş adresinden büyük olamaz."); return
            self.is_scanning_active = True
            self.scan_button.config(state="disabled")
            self.scanning_thread = threading.Thread(target=self._scanning_loop, args=(start_addr, end_addr), daemon=True)
            self.scanning_thread.start()
            self.update_status(f"Aktif portlar taranıyor ({start_addr}-{end_addr})...", "info")
        except ValueError: messagebox.showerror("Giriş Hatası", "Lütfen kayıt ayarları için geçerli sayılar girin.")


    def _scanning_loop(self, start_address, end_address):
        # Arayüzü temizle ve arama kutusunu pasif yap
        self.root.after(0, lambda: [
            self.scan_tree.delete(*self.scan_tree.get_children()),
            self.scan_search_entry.config(state="disabled"),
            self.scan_search_button.config(state="disabled"),
            self.scan_search_var.set("")
        ])
        
        total_count = end_address - start_address + 1
        MAX_REGS_PER_READ = 125; MAX_COILS_PER_READ = 2000
        found_items = []
        try:
            def read_and_process(read_func, result_key, type_str, max_per_read):
                for offset in range(0, total_count, max_per_read):
                    if not self.is_scanning_active: return # Taramayı durdur
                    addr_to_read = start_address + offset
                    num_to_read = min(max_per_read, end_address - addr_to_read + 1)
                    result = read_func(address=addr_to_read, count=num_to_read)
                    if not result.isError():
                        values = getattr(result, result_key)
                        for i, val in enumerate(values[:num_to_read]):
                            current_addr = addr_to_read + i
                            if (type_str == "Coil" and val) or (type_str != "Coil" and val != 0):
                                tag_info = self.tag_cache.get((type_str, current_addr), {}); cihaz = tag_info.get('cihaz_adi', ''); etiket = tag_info.get('etiket_adi', '')
                                found_items.append((cihaz, etiket, current_addr, type_str, str(val)))
            
            read_and_process(self.modbus_client.read_coils, 'bits', "Coil", MAX_COILS_PER_READ)
            read_and_process(self.modbus_client.read_holding_registers, 'registers', "Holding Reg.", MAX_REGS_PER_READ)
            read_and_process(self.modbus_client.read_input_registers, 'registers', "Input Reg.", MAX_REGS_PER_READ)
            
            # --- YENİ: Sonuçları UI'da göster ve arama için kaydet ---
            def update_ui_and_master_list():
                self.scan_tree_items.clear()
                self.scan_tree_item_values.clear()
                for values in found_items:
                    item_id = self.scan_tree.insert("", "end", values=values)
                    self.scan_tree_items.append(item_id)
                    self.scan_tree_item_values[item_id] = values
                # Tarama bittiğinde arama kutusunu aktif et
                if found_items:
                    self.scan_search_entry.config(state="normal")
                    self.scan_search_button.config(state="normal")

            self.root.after(0, update_ui_and_master_list)
            self.update_status(f"Tarama tamamlandı. {len(found_items)} aktif nokta bulundu.", "normal")
        except Exception as e:
            self.update_status(f"Tarama hatası: {e}", "error")
        finally:
            self.is_scanning_active = False
            self.root.after(0, lambda: self.scan_button.config(state="normal"))


if __name__ == "__main__":
    root = tk.Tk()
    app = ModbusApp(root)
    root.mainloop()