import os
import threading
from flask import Flask
import pandas as pd
import pandas_ta as ta
import requests
import telebot
from telebot import types

TG_TOKEN = os.environ.get('TG_TOKEN', 'ВАШ_TELEGRAM_ТОКЕН')
TD_API_KEY = os.environ.get('TD_API_KEY', 'ВАШ_TWELVEDATA_КЛЮЧ')

bot = telebot.TeleBot(TG_TOKEN)
app = Flask(__name__)


@app.route('/')
def home():
  return 'Bot is running!'


def run_web():
  port = int(os.environ.get('PORT', 8080))
  app.run(host='0.0.0.0', port=port)


PAIRS = [
    'EUR/USD',
    'GBP/USD',
    'USD/JPY',
    'USD/CHF',
    'AUD/USD',
    'USD/CAD',
    'NZD/USD',
    'EUR/GBP',
    'EUR/JPY',
    'EUR/CHF',
    'EUR/AUD',
    'EUR/CAD',
    'EUR/NZD',
    'GBP/JPY',
    'GBP/CHF',
    'GBP/AUD',
    'GBP/CAD',
    'GBP/NZD',
    'AUD/JPY',
    'AUD/CHF',
    'AUD/CAD',
    'AUD/NZD',
    'CAD/JPY',
    'CAD/CHF',
    'CHF/JPY',
    'NZD/JPY',
    'NZD/CHF',
    'NZD/CAD',
]

TIMEFRAMES = {'5 хв': '5min', '10 хв': '10min_custom', '15 хв': '15min'}
user_pair = {}


def analyze_market(symbol, tf_code):
  api_interval = '5min' if tf_code == '10min_custom' else tf_code
  output_size = 100 if tf_code == '10min_custom' else 50

  # Виправлена правильна адреса API Twelve Data
  url = f'https://twelvedata.com{symbol}&interval={api_interval}&outputsize={output_size}&apikey={TD_API_KEY}'

  try:
    response = requests.get(url).json()

    if 'values' not in response:
      err_msg = response.get('message', 'Невідома помилка API')
      if 'API credits' in err_msg:
        return '⏳ Забагато запитів за хвилину (ліміт 8/хв). Зачекайте 30 секунд і натисніть знову.'
      return f'⚠️ Помилка отримання даних: {err_msg}'

    df = pd.DataFrame(response['values'])
    df = df.iloc[::-1].reset_index(drop=True)
    df['datetime'] = pd.to_datetime(df['datetime'])
    for col in ['open', 'high', 'low', 'close']:
      df[col] = df[col].astype(float)

    if tf_code == '10min_custom':
      df.set_index('datetime', inplace=True)
      df = (
          df.resample('10min')
          .agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'})
          .dropna()
          .reset_index()
      )

    df['RSI'] = ta.rsi(df['close'], length=14)
    last_rsi = round(df['RSI'].iloc[-1], 1)

    patterns = df.ta.cdl_pattern(name='all')
    last_patterns = patterns.iloc[-1]

    bullish = []
    bearish = []

    for name, val in last_patterns.items():
      clean_name = name.replace('CDL_', '')
      if val > 0:
        bullish.append(clean_name)
      elif val < 0:
        bearish.append(clean_name)

    tf_label = '10 хв' if tf_code == '10min_custom' else tf_code
    msg = f'📊 **Аналіз {symbol} ({tf_label})**\n'
    msg += f'📈 Поточний RSI: **{last_rsi}**\n\n'

    if bullish and last_rsi < 45:
      msg += '🟢 **СИГНАЛ: ВГОРУ (CALL)**\n'
      msg += f"🕯 Патерни: {', '.join(bullish)}"
    elif bearish and last_rsi > 55:
      msg += '🔴 **СИГНАЛ: ВНИЗ (PUT)**\n'
      msg += f"🕯 Патерни: {', '.join(bearish)}"
    elif bullish:
      msg += '🟡 Слабкий сигнал ВГОРУ (RSI не в зоні перепроданості)\n'
      msg += f"🕯 Патерни: {', '.join(bullish)}"
    elif bearish:
      msg += '🟡 Слабкий сигнал ВНИЗ (RSI не в зоні перекупленості)\n'
      msg += f"🕯 Патерни: {', '.join(bearish)}"
    else:
      msg += '⏳ **ЧІТКОГО СИГНАЛУ НЕМАЄ**\nПатернів розвороту не знайдено. Оберіть іншу пару з високою дохідністю.'

    return msg
  except Exception as e:
    return f'❌ Помилка аналізу: {e}'


@bot.message_handler(commands=['start'])
def start(message):
  markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=3)
  markup.add(*[types.KeyboardButton(p) for p in PAIRS])
  bot.send_message(
      message.chat.id,
      'Оберіть валютну пару з актуальною дохідністю на брокері (тільки реальний ринок, без OTC):',
      reply_markup=markup,
  )


@bot.message_handler(func=lambda m: m.text in PAIRS)
def choose_tf(message):
  user_pair[message.chat.id] = message.text
  markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=3)
  markup.add(
      types.KeyboardButton('5 хв'),
      types.KeyboardButton('10 хв'),
      types.KeyboardButton('15 хв'),
      types.KeyboardButton('⬅️ Всі пари'),
  )
  bot.send_message(
      message.chat.id,
      f'Обрано **{message.text}**. Виберіть час експірації:',
      parse_mode='Markdown',
      reply_markup=markup,
  )


@bot.message_handler(func=lambda m: m.text == '⬅️ Всі пари')
def go_back(message):
  start(message)


@bot.message_handler(func=lambda m: m.text in TIMEFRAMES)
def get_signal(message):
  pair = user_pair.get(message.chat.id)
  if not pair:
    return start(message)
  bot.send_message(message.chat.id, f'⏳ Аналізую {pair} ({message.text})...')
  result = analyze_market(pair, TIMEFRAMES[message.text])
  bot.send_message(message.chat.id, result, parse_mode='Markdown')


if __name__ == '__main__':
  threading.Thread(target=run_web, daemon=True).start()
  bot.polling(none_stop=True)
