import os
import logging
import schedule
import time
import threading
import re
import datetime
import sqlite3
import telebot
import matplotlib.pyplot as plt
import matplotlib
from dotenv import load_dotenv
from telebot import types
from datetime import datetime, timedelta
import io

# Настройка Matplotlib для поддержки кириллицы
matplotlib.use('Agg')
matplotlib.rcParams['font.family'] = 'DejaVu Sans'

# Загрузка переменных окружения из .env файла
load_dotenv()

# Получение токена из переменной окружения
BOT_TOKEN = os.getenv('BOT_TOKEN')

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Инициализация бота
bot = telebot.TeleBot(BOT_TOKEN)


# Класс для работы с базой данных
class DatabaseManager:
    def __init__(self, db_name='finance_bot.db'):
        self.db_name = db_name
        self.init_db()

    def get_connection(self):
        """Создает соединение с базой данных."""
        conn = sqlite3.connect(self.db_name)
        conn.row_factory = sqlite3.Row  # Для доступа к столбцам по имени
        return conn

    def init_db(self):
        """Инициализирует базу данных, создавая необходимые таблицы."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Таблица пользователей
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                notifications BOOLEAN DEFAULT TRUE,
                last_activity TEXT
            )
            ''')

            # Таблица категорий
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                name TEXT,
                type TEXT,
                keywords TEXT,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
            ''')

            # Таблица транзакций
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                type TEXT,
                category TEXT,
                amount REAL,
                date TEXT,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
            ''')

            conn.commit()

    def add_user(self, user_id):
        """Добавляет нового пользователя в базу данных."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            # Проверяем, существует ли пользователь
            cursor.execute('SELECT user_id FROM users WHERE user_id = ?', (user_id,))
            if cursor.fetchone() is None:
                cursor.execute(
                    'INSERT INTO users (user_id, last_activity) VALUES (?, ?)',
                    (user_id, now)
                )
                conn.commit()

                # Добавляем стандартные категории для нового пользователя
                self.add_default_categories(user_id)
                return True
            return False

    def add_default_categories(self, user_id):
        """Добавляет стандартные категории для нового пользователя."""
        default_categories = [
            ('Еда', 'expense', 'еда,продукты,супермаркет,магазин'),
            ('Кафе', 'expense', 'кафе,ресторан,бар,кофе,кофейня'),
            ('Доставка', 'expense', 'доставка,яндекс еда,яндекс лавка,лавка'),
            ('Транспорт', 'expense', 'такси,метро,автобус,транспорт,проезд'),
            ('Коммунальные платежи', 'expense', 'квартплата,коммуналка,жкх,вода,электричество,газ,интернет'),
            ('Табак', 'expense', 'сигареты,табак,никотин,вейп,электронная сигарета,электронка'),
            ('Цветы', 'expense', 'цветы,растения,букет'),
            ('Зоотовары', 'expense', 'корм,животные,питомец,кот,собака,ветеринар,ветеринарка'),
            ('Зарплата', 'income', 'зарплата,аванс,получка,стипендия'),
            ('Подработка', 'income', 'подработка,фриланс'),
            ('Подарок', 'income', 'подарок,подарили')
        ]

        with self.get_connection() as conn:
            cursor = conn.cursor()
            for name, type_, keywords in default_categories:
                cursor.execute(
                    'INSERT INTO categories (user_id, name, type, keywords) VALUES (?, ?, ?, ?)',
                    (user_id, name, type_, keywords)
                )
            conn.commit()

    def update_last_activity(self, user_id):
        """Обновляет время последней активности пользователя."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            cursor.execute(
                'UPDATE users SET last_activity = ? WHERE user_id = ?',
                (now, user_id)
            )
            conn.commit()

    def get_all_categories(self, user_id, category_type=None):
        """Получает все категории пользователя."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if category_type:
                cursor.execute(
                    'SELECT * FROM categories WHERE user_id = ? AND type = ?',
                    (user_id, category_type)
                )
            else:
                cursor.execute(
                    'SELECT * FROM categories WHERE user_id = ?',
                    (user_id,)
                )
            return cursor.fetchall()

    def add_category(self, user_id, name, category_type, keywords):
        """Добавляет новую категорию для пользователя."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO categories (user_id, name, type, keywords) VALUES (?, ?, ?, ?)',
                (user_id, name, category_type, keywords)
            )
            conn.commit()
            return cursor.lastrowid

    def delete_category(self, category_id, user_id):
        """Удаляет категорию пользователя."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'DELETE FROM categories WHERE id = ? AND user_id = ?',
                (category_id, user_id)
            )
            conn.commit()
            return cursor.rowcount > 0

    def find_category_by_keyword(self, user_id, text, transaction_type):
        """Находит категорию по ключевому слову."""
        categories = self.get_all_categories(user_id, transaction_type)
        text_lower = text.lower()
        words_in_text = set(text_lower.split())

        for category in categories:
            keywords = [kw.strip().lower() for kw in category['keywords'].split(',') if kw.strip()]
            for keyword in keywords:
                if keyword in text_lower or keyword in words_in_text:
                    return category['name']

        # Если не нашли категорию по ключевым словам
        if transaction_type == 'expense':
            return 'Другое'
        else:
            return 'Другой доход'

    def add_transaction(self, user_id, transaction_type, category, amount, date=None):
        """Добавляет новую транзакцию."""
        if date is None:
            date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO transactions (user_id, type, category, amount, date) VALUES (?, ?, ?, ?, ?)',
                (user_id, transaction_type, category, amount, date)
            )
            conn.commit()
            return cursor.lastrowid

    def get_transactions(self, user_id, start_date=None, end_date=None, category=None, transaction_type=None):
        """Получает транзакции пользователя с возможностью фильтрации."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            query = 'SELECT * FROM transactions WHERE user_id = ?'
            params = [user_id]

            if start_date:
                query += ' AND date >= ?'
                params.append(start_date)

            if end_date:
                query += ' AND date <= ?'
                params.append(end_date)

            if category:
                query += ' AND category = ?'
                params.append(category)

            if transaction_type:
                query += ' AND type = ?'
                params.append(transaction_type)

            query += ' ORDER BY date DESC'

            cursor.execute(query, params)
            return cursor.fetchall()

    def get_categories_summary(self, user_id, start_date=None, end_date=None, transaction_type=None):
        """Получает сумму по категориям за определенный период."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            query = '''
            SELECT category, SUM(amount) as total_amount 
            FROM transactions 
            WHERE user_id = ?
            '''
            params = [user_id]

            if start_date:
                query += ' AND date >= ?'
                params.append(start_date)

            if end_date:
                query += ' AND date <= ?'
                params.append(end_date)

            if transaction_type:
                query += ' AND type = ?'
                params.append(transaction_type)

            query += ' GROUP BY category ORDER BY total_amount DESC'

            cursor.execute(query, params)
            return cursor.fetchall()

    def get_notification_users(self):
        """Получает список пользователей с включенными уведомлениями."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT user_id FROM users WHERE notifications = TRUE')
            return [row['user_id'] for row in cursor.fetchall()]

    def toggle_notifications(self, user_id, status):
        """Включает или выключает уведомления для пользователя."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE users SET notifications = ? WHERE user_id = ?',
                (status, user_id)
            )
            conn.commit()
            return cursor.rowcount > 0

    def get_notification_status(self, user_id):
        """Получает статус уведомлений пользователя."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT notifications FROM users WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()
            return result['notifications'] if result else True


# Создание экземпляра менеджера базы данных
db = DatabaseManager()


# Обновленная функция для проверки формата ввода трат/доходов
def parse_transaction_line(text):
    """
    Парсит строку транзакции и возвращает тип, текст для определения категории и сумму.

    Форматы:
    - Расходы: "категория сумма" (например, "кафе 599р" или "такси 300")
    - Доходы: "+категория сумма" (например, "+зарплата 50000")
    """
    # Удаляем символы валют и другие лишние символы
    text = text.replace('р', '').replace('₽', '').replace('руб', '')

    # Определяем тип транзакции (доход или расход)
    if text.startswith('+'):
        transaction_type = 'income'
        text = text[1:].strip()  # Убираем символ '+' из текста
    else:
        transaction_type = 'expense'

    # Ищем числа в тексте
    numbers = re.findall(r'\b\d+(?:[\.,]\d+)?\b', text)
    if not numbers:
        return None, None, None

    # Предполагаем, что последнее число - это сумма
    amount_str = numbers[-1].replace(',', '.')
    try:
        amount = float(amount_str)
    except ValueError:
        return None, None, None

    # Удаляем сумму из текста для последующего определения категории
    category_text = re.sub(r'\b' + re.escape(numbers[-1]) + r'\b', '', text).strip()

    return transaction_type, category_text, amount


# Обновленная функция для обработки нескольких транзакций
def parse_multiple_transactions(text):
    """
    Парсит текст, содержащий несколько транзакций, разделенных переносом строки.
    Возвращает список кортежей (тип, текст для определения категории, сумма).
    """
    lines = text.strip().split('\n')
    transactions = []

    for line in lines:
        line = line.strip()
        if not line:
            continue

        transaction = parse_transaction_line(line)
        if all(transaction):  # Проверяем, что все элементы транзакции не None
            transactions.append(transaction)

    return transactions


# Функция для создания клавиатуры для времени отчетов
def get_report_period_keyboard():
    """Создает клавиатуру для выбора периода отчета."""
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("День", callback_data='report_day'),
        types.InlineKeyboardButton("Неделя", callback_data='report_week'),
        types.InlineKeyboardButton("Месяц", callback_data='report_month'),
        types.InlineKeyboardButton("Год", callback_data='report_year')
    )
    return markup


# Функция для создания клавиатуры для выбора действия с категориями
def get_categories_keyboard():
    """Создает клавиатуру для управления категориями."""
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("Просмотреть категории расходов", callback_data='view_expense_categories'),
        types.InlineKeyboardButton("Просмотреть категории доходов", callback_data='view_income_categories'),
        types.InlineKeyboardButton("Добавить категорию", callback_data='add_category'),
        types.InlineKeyboardButton("Удалить категорию", callback_data='delete_category')
    )
    return markup


# Функция для получения периода отчета
def get_report_period(period_type):
    """Возвращает начальную и конечную дату для периода отчета."""
    now = datetime.now()

    if period_type == 'day':
        start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = now
    elif period_type == 'week':
        start_date = now - timedelta(days=now.weekday())
        start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = now
    elif period_type == 'month':
        start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end_date = now
    elif period_type == 'year':
        start_date = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        end_date = now
    else:
        return None, None

    return start_date.strftime('%Y-%m-%d %H:%M:%S'), end_date.strftime('%Y-%m-%d %H:%M:%S')


# Функция для создания графика расходов по категориям
def create_category_chart(user_id, start_date, end_date, transaction_type):
    """Создает круговую диаграмму расходов/доходов по категориям."""
    summaries = db.get_categories_summary(user_id, start_date, end_date, transaction_type)

    if not summaries:
        return None

    # Создаем данные для диаграммы
    labels = [summary['category'] for summary in summaries]
    amounts = [summary['total_amount'] for summary in summaries]

    # Создаем круговую диаграмму
    plt.figure(figsize=(10, 7))
    plt.pie(amounts, labels=labels, autopct='%1.1f%%', startangle=90)
    plt.axis('equal')  # Чтобы круг был круглым
    if transaction_type == 'expense':
        title = 'Расходы по категориям'
    else:
        title = 'Доходы по категориям'
    plt.title(title)

    # Сохраняем диаграмму в байтовый поток
    buffer = io.BytesIO()
    plt.savefig(buffer, format='png')
    buffer.seek(0)
    plt.close()

    return buffer


# Обработчик команды /start
@bot.message_handler(commands=['start'])
def start_command(message):
    """Обрабатывает команду /start."""
    user_id = message.from_user.id
    db.add_user(user_id)
    db.update_last_activity(user_id)

    bot.send_message(
        user_id,
        f"👋 Привет, {message.from_user.first_name}! Я бот для учета личных финансов.\n\n"
        "Я помогу тебе вести учет расходов и доходов, а также буду формировать отчеты "
        "и напоминать о необходимости внести траты.\n\n"
        "Чтобы узнать, как мной пользоваться, отправь команду /help"
    )


# Обработчик команды /help
@bot.message_handler(commands=['help'])
def help_command(message):
    """Обрабатывает команду /help."""
    user_id = message.from_user.id
    db.update_last_activity(user_id)

    help_text = (
        "🤖 *Команды бота:*\n\n"
        "/start - начало работы с ботом\n"
        "/help - показать эту справку\n"
        "/report - сформировать отчет за период\n"
        "/categories - управление категориями\n"
        "/notifications - управление уведомлениями\n\n"

        "📝 *Как вносить траты и доходы:*\n\n"
        "Чтобы добавить расход, просто напиши: `категория сумма`\n"
        "Например: `кафе 500` или `такси 300р`\n\n"

        "Чтобы добавить доход, напиши: `+категория сумма`\n"
        "Например: `+зарплата 50000` или `+подработка 5000р`\n\n"

        "🔢 *Несколько транзакций за раз:*\n"
        "Можно вносить несколько транзакций в одном сообщении, разделяя их переводом строки:\n"
        "```\nкафе 500\nтакси 300\n+зарплата 50000```\n\n"

        "Бот автоматически определит категорию по ключевым словам.\n"
        "Если категория не определена, транзакция будет добавлена в 'Другое' или 'Другой доход'."
    )

    bot.send_message(user_id, help_text, parse_mode='Markdown')


# Обработчик команды /report
@bot.message_handler(commands=['report'])
def report_command(message):
    """Обрабатывает команду /report."""
    user_id = message.from_user.id
    db.update_last_activity(user_id)

    bot.send_message(
        user_id,
        "📊 Выберите период для формирования отчета:",
        reply_markup=get_report_period_keyboard()
    )


# Обработчик команды /categories
@bot.message_handler(commands=['categories'])
def categories_command(message):
    """Обрабатывает команду /categories."""
    user_id = message.from_user.id
    db.update_last_activity(user_id)

    bot.send_message(
        user_id,
        "🗂 Управление категориями:",
        reply_markup=get_categories_keyboard()
    )


# Обработчик команды /notifications
@bot.message_handler(commands=['notifications'])
def notifications_command(message):
    """Обрабатывает команду /notifications."""
    user_id = message.from_user.id
    db.update_last_activity(user_id)

    current_status = db.get_notification_status(user_id)

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton(
            "Включить ✅" if not current_status else "Уже включены ✅",
            callback_data='toggle_notifications_on' if not current_status else 'no_action'
        ),
        types.InlineKeyboardButton(
            "Выключить ❌" if current_status else "Уже выключены ❌",
            callback_data='toggle_notifications_off' if current_status else 'no_action'
        )
    )

    status_text = "включены ✅" if current_status else "выключены ❌"
    bot.send_message(
        user_id,
        f"🔔 Ежедневные напоминания сейчас {status_text}\n\nВыберите действие:",
        reply_markup=markup
    )


# Обработчик колбэков от инлайн-клавиатур
@bot.callback_query_handler(func=lambda call: True)
def handle_callback_query(call):
    """Обрабатывает все колбэки от инлайн-клавиатур."""
    user_id = call.from_user.id
    db.update_last_activity(user_id)

    # Обработка колбэков для отчетов
    if call.data.startswith('report_'):
        period_type = call.data.split('_')[1]
        generate_report(user_id, period_type)

    # Обработка колбэков для категорий
    elif call.data.startswith('view_'):
        category_type = call.data.split('_')[1]
        view_categories(user_id, category_type)

    elif call.data == 'add_category':
        bot.send_message(
            user_id,
            "Введите новую категорию в формате:\n"
            "`тип название ключевые_слова`\n\n"
            "Типы: expense (расход) или income (доход)\n"
            "Пример: `expense Такси такси,яндекс,убер,каршеринг`"
        )
        # Устанавливаем следующий шаг обработки
        bot.register_next_step_handler(call.message, process_new_category)

    elif call.data == 'delete_category':
        # Показываем список категорий для удаления
        show_categories_for_deletion(user_id)

    elif call.data.startswith('delete_category_'):
        category_id = int(call.data.split('_')[2])
        if db.delete_category(category_id, user_id):
            bot.send_message(user_id, "✅ Категория успешно удалена!")
        else:
            bot.send_message(user_id, "❌ Не удалось удалить категорию.")

    # Обработка колбэков для уведомлений
    elif call.data == 'toggle_notifications_on':
        db.toggle_notifications(user_id, True)
        bot.send_message(user_id, "✅ Уведомления включены!")

    elif call.data == 'toggle_notifications_off':
        db.toggle_notifications(user_id, False)
        bot.send_message(user_id, "❌ Уведомления выключены!")

    # Подтверждаем обработку колбэка
    bot.answer_callback_query(call.id)


# Обработчик для добавления новой категории
def process_new_category(message):
    """Обрабатывает ввод новой категории."""
    user_id = message.from_user.id
    text = message.text.strip()

    parts = text.split(' ', 2)
    if len(parts) < 3:
        bot.send_message(
            user_id,
            "❌ Неверный формат. Пожалуйста, используйте формат:\n"
            "`тип название ключевые_слова`"
        )
        return

    category_type, name, keywords = parts

    if category_type not in ['expense', 'income']:
        bot.send_message(
            user_id,
            "❌ Неверный тип категории. Используйте 'expense' для расходов или 'income' для доходов."
        )
        return

    if db.add_category(user_id, name, category_type, keywords):
        bot.send_message(
            user_id,
            f"✅ Категория '{name}' успешно добавлена!"
        )
    else:
        bot.send_message(
            user_id,
            "❌ Не удалось добавить категорию."
        )


# Функция для отображения категорий
def view_categories(user_id, category_type):
    """Отображает список категорий определенного типа."""
    categories = db.get_all_categories(user_id, category_type)

    if not categories:
        bot.send_message(
            user_id,
            f"У вас нет категорий типа '{category_type}'."
        )
        return

    type_name = "расходов" if category_type == "expense" else "доходов"
    response = f"📋 Ваши категории {type_name}:\n\n"

    for category in categories:
        response += f"• *{category['name']}*\n"
        response += f"  Ключевые слова: _{category['keywords']}_\n\n"

    bot.send_message(user_id, response, parse_mode='Markdown')


# Функция для отображения категорий для удаления
def show_categories_for_deletion(user_id):
    """Показывает инлайн-клавиатуру для выбора категории для удаления."""
    categories = db.get_all_categories(user_id)

    if not categories:
        bot.send_message(user_id, "У вас нет категорий для удаления.")
        return

    markup = types.InlineKeyboardMarkup(row_width=1)

    for category in categories:
        type_name = "расход" if category['type'] == "expense" else "доход"
        button_text = f"{category['name']} ({type_name})"
        callback_data = f"delete_category_{category['id']}"
        markup.add(types.InlineKeyboardButton(button_text, callback_data=callback_data))

    bot.send_message(
        user_id,
        "Выберите категорию для удаления:",
        reply_markup=markup
    )


# Функция для генерации отчета
def generate_report(user_id, period_type):
    """Генерирует и отправляет отчет за указанный период."""
    start_date, end_date = get_report_period(period_type)

    if not start_date or not end_date:
        bot.send_message(user_id, "❌ Неверный период для отчета.")
        return

    # Получаем транзакции за указанный период
    expenses = db.get_transactions(user_id, start_date, end_date, transaction_type='expense')
    incomes = db.get_transactions(user_id, start_date, end_date, transaction_type='income')

    # Считаем общие суммы
    total_expense = sum(expense['amount'] for expense in expenses)
    total_income = sum(income['amount'] for income in incomes)
    balance = total_income - total_expense

    # Форматируем период для отображения
    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d %H:%M:%S')
    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d %H:%M:%S')

    period_format = {
        'day': f"{start_date_obj.strftime('%d.%m.%Y')}",
        'week': f"{start_date_obj.strftime('%d.%m.%Y')} - {end_date_obj.strftime('%d.%m.%Y')}",
        'month': f"{start_date_obj.strftime('%B %Y')}",
        'year': f"{start_date_obj.strftime('%Y')}"
    }

    period_display = period_format.get(period_type, '')

    # Формируем текст отчета
    report_text = f"📊 *Отчет за {period_display}*\n\n"

    report_text += f"💰 *Доходы:* {total_income:.2f} ₽\n"
    report_text += f"💸 *Расходы:* {total_expense:.2f} ₽\n"
    report_text += f"📈 *Баланс:* {balance:.2f} ₽\n\n"

    # Создаем и отправляем графики по категориям, если есть данные
    if expenses:
        expense_chart = create_category_chart(user_id, start_date, end_date, 'expense')
        if expense_chart:
            bot.send_message(user_id, report_text, parse_mode='Markdown')
            bot.send_photo(user_id, expense_chart, caption="📉 Расходы по категориям")
        else:
            bot.send_message(user_id, report_text + "По расходам нет данных для создания графика.",
                             parse_mode='Markdown')
    else:
        report_text += "По расходам нет данных для создания графика.\n\n"

    if incomes:
        income_chart = create_category_chart(user_id, start_date, end_date, 'income')
        if income_chart:
            if not expenses:  # Если отчет еще не отправлен
                bot.send_message(user_id, report_text, parse_mode='Markdown')
            bot.send_photo(user_id, income_chart, caption="📈 Доходы по категориям")
        else:
            if not expenses:  # Если отчет еще не отправлен
                bot.send_message(user_id, report_text + "По доходам нет данных для создания графика.",
                                 parse_mode='Markdown')
    else:
        if not expenses:  # Если отчет еще не отправлен
            report_text += "По доходам нет данных для создания графика.\n"
            bot.send_message(user_id, report_text, parse_mode='Markdown')

    # Отправляем детализацию транзакций
    if expenses or incomes:
        all_transactions = db.get_transactions(user_id, start_date, end_date)
        if len(all_transactions) > 15:
            # Если транзакций много, отправляем только последние 15
            bot.send_message(
                user_id,
                "🧾 *Последние транзакции:*\n\n" + format_transactions(
                    all_transactions[:15]) + "\n\n_Показаны только последние 15 транзакций_",
                parse_mode='Markdown'
            )
        else:
            bot.send_message(
                user_id,
                "🧾 *Все транзакции за период:*\n\n" + format_transactions(all_transactions),
                parse_mode='Markdown'
            )


# Функция для форматирования списка транзакций
def format_transactions(transactions):
    """Форматирует список транзакций для отображения."""
    if not transactions:
        return "Нет транзакций."

    result = ""
    for tx in transactions:
        date_obj = datetime.strptime(tx['date'], '%Y-%m-%d %H:%M:%S')
        date_str = date_obj.strftime('%d.%m.%Y %H:%M')

        # Определяем символ для типа транзакции
        symbol = "➖" if tx['type'] == 'expense' else "➕"

        result += f"{date_str} {symbol} *{tx['category']}*: {tx['amount']:.2f} ₽\n"

    return result


# Функция для отправки ежедневных напоминаний
def send_daily_reminders():
    """Отправляет ежедневные напоминания пользователям."""
    logger.info("Отправка ежедневных напоминаний...")
    users = db.get_notification_users()

    current_hour = datetime.now().hour
    reminder_text = f"🔔 Не забудьте внести сегодняшние расходы и доходы!"

    for user_id in users:
        try:
            bot.send_message(user_id, reminder_text)
            logger.info(f"Напоминание отправлено пользователю {user_id}")
        except Exception as e:
            logger.error(f"Ошибка при отправке напоминания пользователю {user_id}: {e}")


# Запускаем планировщик в отдельном потоке
def run_scheduler():
    """Запускает планировщик задач в отдельном потоке."""
    # Планируем ежедневное напоминание на 21:00
    schedule.every().day.at("21:00").do(send_daily_reminders)

    while True:
        schedule.run_pending()
        time.sleep(60)  # Проверяем раз в минуту


# Обработчик для всех текстовых сообщений
@bot.message_handler(func=lambda message: True)
def handle_message(message):
    """Обрабатывает все текстовые сообщения как возможные транзакции."""
    user_id = message.from_user.id
    db.update_last_activity(user_id)
    text = message.text.strip()

    # Проверяем, содержит ли сообщение несколько строк
    if '\n' in text:
        # Парсим несколько транзакций
        transactions = parse_multiple_transactions(text)

        if not transactions:
            # Если не распознали ни одной транзакции
            bot.send_message(
                user_id,
                "❌ Не удалось распознать транзакции. Используйте формат:\n"
                "- Для расходов: `категория сумма`\n"
                "- Для доходов: `+категория сумма`\n\n"
                "Например:\n"
                "```\nкафе 500\nдоставка 600\n+зарплата 50000```\n\n"
                "Отправьте /help для получения справки."
            )
            return

        # Обрабатываем каждую транзакцию
        response = "✅ Добавлены транзакции:\n\n"
        success_count = 0

        for transaction in transactions:
            transaction_type, category_text, amount = transaction

            # Находим подходящую категорию
            category = db.find_category_by_keyword(user_id, category_text, transaction_type)

            # Добавляем транзакцию
            db.add_transaction(user_id, transaction_type, category, amount)

            # Добавляем информацию о транзакции в ответ
            type_emoji = "💸" if transaction_type == 'expense' else "💰"
            response += f"{type_emoji} *{category}*: {amount:.2f} ₽\n"
            success_count += 1

        if success_count > 0:
            response += f"\nВсего добавлено: {success_count} транзакций."
            bot.send_message(user_id, response, parse_mode='Markdown')
        else:
            bot.send_message(
                user_id,
                "❌ Не удалось распознать ни одной транзакции. Проверьте формат ввода."
            )
    else:
        # Обрабатываем одиночную транзакцию (существующий код)
        # Пробуем распарсить транзакцию
        transaction_type, category_text, amount = parse_transaction_line(text)

        if transaction_type and amount:
            # Находим подходящую категорию
            category = db.find_category_by_keyword(user_id, category_text, transaction_type)

            # Добавляем транзакцию
            db.add_transaction(user_id, transaction_type, category, amount)

            # Формируем ответное сообщение
            type_emoji = "💸" if transaction_type == 'expense' else "💰"
            response = f"{type_emoji} Добавлено: *{category}* {amount:.2f} ₽"

            bot.send_message(user_id, response, parse_mode='Markdown')
        else:
            # Если не распознали транзакцию
            bot.send_message(
                user_id,
                "❌ Не удалось распознать транзакцию. Используйте формат:\n"
                "- Для расходов: `категория сумма`\n"
                "- Для доходов: `+категория сумма`\n\n"
                "Например: `кафе 500` или `+зарплата 50000`\n\n"
                "Отправьте /help для получения справки."
            )


if __name__ == "__main__":
    # Запускаем планировщик в отдельном потоке
    scheduler_thread = threading.Thread(target=run_scheduler)
    scheduler_thread.daemon = True
    scheduler_thread.start()

    # Запускаем бота
    logger.info("Бот запущен")
    bot.polling(none_stop=True)