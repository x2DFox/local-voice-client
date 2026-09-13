from tkinter import Tk, PhotoImage, ttk, Menu, IntVar, BooleanVar, Toplevel, messagebox, Text
import numpy as np  # pip install numpy
import pyaudio      # pip install pyaudio
import configparser
import webbrowser
import threading
import socket
import string
import time

############################################################

CONFIG_PATH = "config.ini"
config = configparser.ConfigParser()

DEFAULTS = {
    "show_warning": "True",
}


def load_config():
    config.read(CONFIG_PATH, encoding="UTF-8")
    if config.has_option("main", "show_warning"):
        return
    config["main"] = DEFAULTS.copy()
    save_config()


def save_config():
    with open(CONFIG_PATH, "w", encoding="UTF-8") as f:
        config.write(f)


def warning_window():
    window = Toplevel(root)
    window.title("Шифрование не реализовано")
    window.geometry("400x200")
    window.resizable(width=False, height=False)
    window.grab_set()
    window.focus_force()

    txt = ("Пароль и аудио передаются в открытом виде независимо от того,\nлокальная это сеть или публичный адрес.\n"
           "Если сервер доступен из интернета - любой сможет подслушать\nразговор и узнать пароль.\n")
    ttk.Label(window, text=txt).place(x=10, y=10)

    understand = BooleanVar(value=False)
    dont_show = BooleanVar(value=False)

    def toggle_continue():
        status = "normal" if understand.get() else "disabled"
        continue_button.config(state=status)
        dont_show_check.config(state=status)

    def close_window():
        if dont_show.get():
            config["main"]["show_warning"] = "False"
            save_config()
        window.destroy()
        root.deiconify()

    def close_app():
        window.destroy()
        root.destroy()

    ttk.Checkbutton(window, text="Я понимаю и хочу продолжить",
                    variable=understand, command=toggle_continue).place(x=10, y=95)
    dont_show_check = ttk.Checkbutton(window, text="Больше не показывать", variable=dont_show, state="disabled")
    dont_show_check.place(x=10, y=115)

    continue_button = ttk.Button(window, text="Продолжить", state="disabled", command=close_window)
    continue_button.place(x=10, y=165, width=185)
    ttk.Button(window, text="Закрыть", command=close_app).place(x=205, y=165, width=185)

    window.protocol("WM_DELETE_WINDOW", close_app)

############################################################


# Перехватываем комбинации CTRL+A/C/V/X в полях ввода
def block_input(event, is_entry=False):
    if event.state & 0x0004 and event.keycode == 65:
        event.widget.event_generate("<<SelectAll>>")
        return "break"
    if event.state & 0x0004 and event.keycode == 67:
        event.widget.event_generate("<<Copy>>")
        return "break"
    if event.state & 0x0004 and event.keycode == 86:
        if is_entry:
            event.widget.event_generate("<<Paste>>")
            return "break"
        return "break"
    if event.state & 0x0004 and event.keycode == 88:
        if is_entry:
            event.widget.event_generate("<<Cut>>")
            return "break"
        return "break"
    if is_entry:
        return None
    return "break"


# Открываем дочернее окно один раз, повторный вызов поднимает уже открытое
def custom_window(name, title, dev=False):
    if hasattr(root, name) and getattr(root, name) is not None:
        getattr(root, name).lift()
        getattr(root, name).focus()
        return

    window = Toplevel(root)
    window.title(title)
    window.resizable(width=False, height=False)
    window.focus()

    if dev:
        ttk.Label(window, image=IMAGE).pack(padx=10, pady=10)
    else:
        txt = Text(window, relief="solid", font=("TkDefaultFont"), wrap="word", width=83, height=26)
        with open("LICENSE.txt", "r", encoding="UTF-8") as f:
            content = f.read()
        txt.insert("1.0", content)
        txt.config(state="disabled")
        txt.bind("<Key>", block_input)
        txt.pack(padx=10, pady=10)

    def close_window():
        window.destroy()
        setattr(root, name, None)

    window.protocol("WM_DELETE_WINDOW", close_window)
    setattr(root, name, window)


def version():
    messagebox.showinfo(title="Версия", message="v0.2.2 [BETA]\n\n"
                                                "- Упорядочено меню информации\n"
                                                "- Добавлен файл конфигурации\n"
                                                "- Заменен устаревший audioop на numpy\n"
                                                "- Устранены исключения в аудио-потоках при отключении\n"
                                                "- Реализована базовая валидация IP-Адреса\n"
                                                "- Добавлена проверка порта и пароля\n"
                                                "- Отлажены горячие клавиши в полях ввода для Windows")


def developer(x2dfox=False, git=False):
    if x2dfox:
        custom_window(name="image_window", title="x2DFox", dev=True)
    elif git:
        choice = messagebox.askyesno(title="GitHub", message="Перейти на страницу разработчика?")
        if choice:
            webbrowser.open("https://github.com/x2DFox")
    else:
        choice = messagebox.askyesno(title="Telegram", message="Перейти в канал разработчика?")
        if choice:
            webbrowser.open("https://t.me/x2DFox")


def license():
    custom_window(name="license_window", title="BSD 3-Clause License")


############################################################

# Параметры звука
CHANNELS = 1              # Моно-канал
CHUNK = 1024              # Размер аудио-пакета
RATE = 44100              # Частота дискретизации
FORMAT = pyaudio.paInt16  # 16-и битное аудио

# Глобальные переменные
sock = None               # Сокет для соединения с сервером
stream = None             # Поток для воспроизведения звука
stream_in = None          # Поток для записи звука
audio = None              # Аудио-объект
connected = False         # Флаг подключения к серверу

############################################################


# Обновляет отображение значений усиления и громкости
def change(*args):
    micgain_label["text"] = f"Усиление: {micgain.get()} дБ"
    speaker_label["text"] = f"Громкость: {speaker.get()}%"


# Изменяет усиление на delta dB
def regulator_gain(delta):
    current = micgain.get()
    nvalue = (current + delta)
    if -30 <= nvalue <= 30:
        micgain.set(nvalue)
        change()


# Изменяет громкость на delta %
def regulator_volume(delta):
    current = speaker.get()
    nvalue = (current + delta)
    if 0 <= nvalue <= 200:
        speaker.set(nvalue)
        change()


# Применяет усиление к аудиоданным
def apply_gain(data, gain):
    if gain == 0:
        return data
    volume = 10 ** (gain / 20)                                     # Преобразуем dB в линейный множитель
    samples = np.frombuffer(data, dtype='<i2').astype(np.float32)  # Байты в массив int16, делаем копию в float32
    samples *= volume                                              # Умножаем каждый сэмпл на множитель
    samples = np.clip(samples, -32768, 32767).astype('<i2')        # Обрезаем по границам int16 и возвращаем тип int16
    return samples.tobytes()                                       # Массив в байты (для отправки на сервер)


# Применяем громкость к аудиоданным
def apply_volume(data, volume):
    if volume == 100:
        return data
    factor = volume / 100                                          # Проценты в множитель (50 в 0.5, 200 в 2.0)
    samples = np.frombuffer(data, dtype='<i2').astype(np.float32)  # Байты в массив int16, делаем копию в float32
    samples *= factor                                              # Умножаем каждый сэмпл на множитель
    samples = np.clip(samples, -32768, 32767).astype('<i2')        # Обрезаем по границам int16 и возвращаем тип int16
    return samples.tobytes()                                       # Массив в байты (для воспроизведения)


############################################################


# Проверяем введенные данные, подключаемся к серверу, проходим аутентификацию и запускаем аудио-потоки
def connect():
    global sock, stream, stream_in, audio, connected

    ip = ip_entry.get().strip()
    allowed = set(string.ascii_letters + string.digits + ".-:")  # Белый список символов для IP-адреса или домена
    port_str = port_entry.get().strip()
    password = password_entry.get()

    if not nickname_entry.get().strip():  # Проверяем, что никнейм введен
        messagebox.showerror(title="Ошибка", message="Введите имя")
        return
    if not ip:  # Проверяем, что IP введен
        messagebox.showerror(title="Ошибка", message="Введите IP-Адрес")
        return
    for ch in ip:
        if ch not in allowed:
            messagebox.showerror("Ошибка", f"Недопустимый символ в IP-Адресе: {ch}")
            return
    if not port_str:  # Проверяем порт
        messagebox.showerror(title="Ошибка", message="Введите порт")
        return
    try:
        port = int(port_str)
        if not (49152 <= port <= 65535):
            messagebox.showerror(title="Ошибка", message="Порт: неверный диапазон")
            return
    except ValueError:
        messagebox.showerror(title="Ошибка", message="Порт: нечисловое значение")
        return
    if not password:  # Проверяем пароль
        messagebox.showerror(title="Ошибка", message="Введите пароль")
        return
    if len(password) < 8 or len(password) > 32:
        messagebox.showerror(title="Ошибка", message="Пароль должен быть от 8-и до 32-х символов")
        return
    if " " in password:
        messagebox.showerror(title="Ошибка", message="Пароль не должен содержать пробелы")
        return

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)  # Создаем клиентский сокет (IPv4, TCP)
        sock.connect((ip, port))                                  # Подключаемся по IP и порту

        sock.send(password.encode())                           # Отправляем пароль на сервер
        if sock.recv(1024).decode() == "BAD":                  # Сервер отвечает "OK" или "BAD"
            messagebox.showerror("Ошибка", "Неверный пароль")  # Если пароль неверный, показываем ошибку
            sock.close()                                       # Закрываем сокет
            sock = None                                        # Обнуляем сокет
            return

        sock.send(nickname_entry.get().encode())  # Отправляем никнейм на сервер

        # Инициализируем два независимых потока: один на воспроизведение, другой на запись
        audio = pyaudio.PyAudio()
        # Настраиваем аудио для воспроизведения
        stream = audio.open(format=FORMAT,
                            channels=CHANNELS,
                            rate=RATE,
                            output=True,    # Режим воспроизведения
                            frames_per_buffer=CHUNK)
        # Настраиваем аудио для записи
        stream_in = audio.open(format=FORMAT,
                               channels=CHANNELS,
                               rate=RATE,
                               input=True,  # Режим записи
                               frames_per_buffer=CHUNK)

        # Меняем состояние программы
        connected = True                                           # Подключены
        connect_button.config(text="ОТКЛЮЧИТЬСЯ")                  # Текст кнопки
        status_label.config(text="ПОДКЛЮЧЕН", foreground="green")  # Статус

        # Блокируем поля ввода
        nickname_entry.config(state="disabled")
        ip_entry.config(state="disabled")
        port_entry.config(state="disabled")
        password_entry.config(state="disabled")

        # Запускаем потоки для работы с аудио
        threading.Thread(target=receive_audio, daemon=True).start()  # Для приема
        threading.Thread(target=send_audio, daemon=True).start()     # Для отправки

    # Если хоть что-то пошло не так, показываем ошибку
    except Exception as e:
        messagebox.showerror(title="Ошибка", message=f"Подключение прервано: {e}")
        # Если произошла ошибка - то обнуляем все, что успели создать
        if sock:
            sock.close()       # Закрываем сокет
            sock = None        # Обнуляем
        if stream:
            stream.close()     # Закрываем аудио-поток воспроизведения
            stream = None      # Обнуляем
        if stream_in:
            stream_in.close()  # Закрываем аудио-поток записи
            stream_in = None   # Обнуляем
        if audio:
            audio.terminate()  # Закрываем аудио-подсистему
            audio = None       # Обнуляем


# Закрываем сокет и аудио-потоки, возвращаем интерфейс в исходное состояние
def disconnect():
    global sock, stream, stream_in, audio, connected

    # Сбрасываем флаг подключения
    connected = False

    if sock:
        sock.close()             # Закрываем сокет
        sock = None              # Обнуляем
    if stream:
        stream.stop_stream()     # Останавливаем аудио-поток воспроизведения
        stream.close()           # Закрываем аудио-поток воспроизведения
        stream = None            # Обнуляем
    if stream_in:
        stream_in.stop_stream()  # Останавливаем аудио-поток записи
        stream_in.close()        # Закрываем аудио-поток записи
        stream_in = None         # Обнуляем
    if audio:
        audio.terminate()        # Завершаем аудио
        audio = None             # Обнуляем

    # Сбрасываем интерфейс
    connect_button.config(text="ПОДКЛЮЧИТЬСЯ")
    status_label.config(text="ОТКЛЮЧЕН", foreground="red")

    # Разблокируем поля ввода
    nickname_entry.config(state="normal")
    ip_entry.config(state="normal")
    port_entry.config(state="normal")
    password_entry.config(state="normal")


# Постоянно читаем аудио из сокета и пишем его в поток воспроизведения
def receive_audio():
    while connected:
        local_sock = sock                                     # Берем ссылку один раз
        if local_sock is None:                                # Сокет уже закрыт - выходим
            break
        try:

            data = local_sock.recv(CHUNK)                     # Получаем аудио-пакет от сервера
            if not data:                                      # Если данных нет - сервер отключился
                break
            if stream is not None and speaker_toggle.get():   # Проверяем, что поток существует и динамики включены
                data = apply_volume(data, speaker.get())      # Применяем громкость
                stream.write(data)                            # Воспроизводим полученное аудио
        except OSError:
            break                                             # При ошибке выходим из цикла

    # Если отключение произведено не нами - вызываем отключение в главном потоке
    if connected:
        root.after(0, disconnect)


# Постоянно читаем микрофон и шлем данные на сервер
def send_audio():
    # Цикл записи и отправки
    while connected:
        local_sock = sock                                                  # Берем ссылку один раз
        if local_sock is None or stream_in is None:                        # Сокет уже закрыт - выходим
            break
        try:
            if microphone_toggle.get():                                    # Если микрофон включен
                data = stream_in.read(CHUNK, exception_on_overflow=False)  # Читаем с микрофона
                data = apply_gain(data, micgain.get())                     # Применяем усиление
                local_sock.send(data)                                      # Отправляем на сервер
            else:                                                          # Если микрофон выключен
                time.sleep(0.001)                                          # Задержка, чтобы не грузить CPU и сеть

        except OSError:
            break                                                          # При ошибке выходим из цикла


# Переключаем состояние кнопки "ПОДКЛЮЧИТЬСЯ/ОТКЛЮЧИТЬСЯ"
def toggle():
    if not connected:
        connect()
    else:
        disconnect()


############################################################

root = Tk()
root.withdraw()
root.title("Local Voice [CLIENT]")
icon = PhotoImage(file="resources/16x16.png")
root.iconphoto(True, icon)
root.geometry("300x350")
root.resizable(width=False, height=False)

main_menu = Menu(tearoff=0)
file_menu = Menu(tearoff=0)
developer_menu = Menu(tearoff=0)

file_menu.add_command(label="Версия", command=version)
file_menu.add_cascade(label="Разработчик", menu=developer_menu)
file_menu.add_command(label="Лицензия", command=license)

developer_menu.add_command(label="x2DFox", command=lambda: developer(x2dfox=True))
IMAGE = PhotoImage(file="resources/developer.png")
developer_menu.add_command(label="GitHub", command=lambda: developer(git=True))
developer_menu.add_command(label="Telegram", command=lambda: developer())

main_menu.add_cascade(label="Информация", menu=file_menu)
root.config(menu=main_menu)

ttk.Frame(relief="solid").place(x=0, y=15, width=300, height=0)
ttk.Label(text="Данные для подключения").place(x=75, y=5)

ttk.Label(text="Имя").place(x=10, y=20)
nickname_entry = ttk.Entry()
nickname_entry.bind("<Key>", lambda e: block_input(e, is_entry=True))
nickname_entry.place(x=10, y=40, width=280)

ttk.Label(text="IP-Адрес").place(x=10, y=70)
ip_entry = ttk.Entry()
ip_entry.bind("<Key>", lambda e: block_input(e, is_entry=True))
ip_entry.place(x=10, y=90, width=185)

ttk.Label(text="Порт").place(x=200, y=70)
port_entry = ttk.Entry()
port_entry.bind("<Key>", lambda e: block_input(e, is_entry=True))
port_entry.place(x=200, y=90, width=90)

ttk.Label(text="Пароль").place(x=10, y=120)
password_entry = ttk.Entry(show="*")
password_entry.bind("<Key>", lambda e: block_input(e, is_entry=True))
password_entry.place(x=10, y=140, width=280)

ttk.Frame(relief="solid").place(x=0, y=180, width=300, height=0)
ttk.Label(text="Настройки").place(x=115, y=170)

microphone_toggle = BooleanVar(value=True)
speaker_toggle = BooleanVar(value=True)
ttk.Checkbutton(text="Микрофон  [ I / O ]", variable=microphone_toggle).place(x=10, y=215)
ttk.Checkbutton(text="Наушники  [ I / O ]", variable=speaker_toggle).place(x=10, y=265)

micgain = IntVar(value=0)
micgain_label = ttk.Label(text=f"Усиление: {micgain.get()} дБ")
micgain_label.place(x=150, y=195)

ttk.Button(text="<", command=lambda: regulator_gain(-1), width=1).place(x=150, y=215)
ttk.Scale(from_=-30, to=30, orient="horizontal", variable=micgain, command=change, length=110).place(x=165, y=215)
ttk.Button(text=">", command=lambda: regulator_gain(1), width=1).place(x=275, y=215)

speaker = IntVar(value=100)
speaker_label = ttk.Label(text=f"Громкость: {speaker.get()} %")
speaker_label.place(x=150, y=245)

ttk.Button(text="<", command=lambda: regulator_volume(-1), width=1).place(x=150, y=265)
ttk.Scale(from_=0, to=200, orient="horizontal", variable=speaker, command=change, length=110).place(x=165, y=265)
ttk.Button(text=">", command=lambda: regulator_volume(1), width=1).place(x=275, y=265)

ttk.Frame(relief="solid").place(x=0, y=305, width=300, height=0)
ttk.Label(text="Статус:").place(x=10, y=295)
status_label = ttk.Label(text="ОТКЛЮЧЕН", foreground="red")
status_label.place(x=50, y=295)

connect_button = ttk.Button(text="ПОДКЛЮЧИТЬСЯ", command=toggle)
connect_button.place(x=10, y=315, width=280)

load_config()
if config.getboolean("main", "show_warning", fallback=True):
    warning_window()
else:
    root.deiconify()

root.mainloop()
