import os
import asyncio
import math
import logging
import copy
from itertools import combinations

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove

# --- Класс Дробей ---
class Fraction:
    def __init__(self, numerator, denominator=1):
        if denominator == 0:
            raise ZeroDivisionError("Знаменатель не может быть нулем.")
        common = math.gcd(abs(numerator), abs(denominator))
        sign = 1 if (numerator > 0) == (denominator > 0) else -1
        if numerator == 0: sign = 1
        self.num = abs(numerator) // common * sign
        self.den = abs(denominator) // common

    def __add__(self, other):
        if not isinstance(other, Fraction): other = Fraction(other)
        return Fraction(self.num * other.den + other.num * self.den, self.den * other.den)

    def __sub__(self, other):
        if not isinstance(other, Fraction): other = Fraction(other)
        return Fraction(self.num * other.den - other.num * self.den, self.den * other.den)

    def __mul__(self, other):
        if not isinstance(other, Fraction): other = Fraction(other)
        return Fraction(self.num * other.num, self.den * other.den)

    def __truediv__(self, other):
        if not isinstance(other, Fraction): other = Fraction(other)
        if other.num == 0: raise ZeroDivisionError("Деление на ноль.")
        return Fraction(self.num * other.den, self.den * other.num)

    def __eq__(self, other):
        if not isinstance(other, Fraction): other = Fraction(other)
        return self.num == other.num and self.den == other.den

    def __repr__(self):
        return str(self.num) if self.den == 1 else f"{self.num}/{self.den}"

# --- Состояния ---
class MatrixStates(StatesGroup):
    waiting_for_matrix = State()
    waiting_for_basis = State()

# --- Вспомогательные функции ---

def format_matrix_to_str(matrix, message=""):
    """Форматирует матрицу в блок кода для Telegram с 1 пробелом между числами"""
    res = []
    if message:
        res.append(f"<b>👉 {message}</b>")
    
    table = []
    for row in matrix:
        # ЗАМЕНА: тут был "  ", стал " "
        table.append(" ".join(f"{str(x):>7}" for x in row))
    
    # Добавляем <pre>, чтобы сохранить ровные колонки
    final_block = "\n".join(res) + "\n<pre>" + "\n".join(table) + "</pre>\n" + "—" * 20
    return final_block

def compute_rank(matrix_in):
    A = copy.deepcopy(matrix_in)
    m, n = len(A), len(A[0])
    row = 0
    for col in range(n):
        if row >= m: break
        pivot = -1
        for i in range(row, m):
            if A[i][col].num != 0:
                pivot = i
                break
        if pivot == -1: continue
        A[row], A[pivot] = A[pivot], A[row]
        div = A[row][col]
        for j in range(col, n): A[row][j] = A[row][j] / div
        for i in range(m):
            if i != row:
                factor = A[i][col]
                if factor.num != 0:
                    for j in range(col, n): A[i][j] = A[i][j] - factor * A[row][j]
        row += 1
    return sum(1 for r in A if any(x.num != 0 for x in r))

def get_basic_solution_log(original_matrix, basis_indices):
    matrix = copy.deepcopy(original_matrix)
    m, n_vars = len(matrix), len(matrix[0]) - 1
    logs = []

    for step, col_idx in enumerate(basis_indices):
        pivot_row = -1
        for r in range(step, m):
            if matrix[r][col_idx].num != 0:
                pivot_row = r
                break 
        
        if pivot_row == -1:
            return None, [f"❌ Столбец x{col_idx+1} лин. зависим."]

        # 1. Перестановка (Swap)
        if pivot_row != step:
            matrix[step], matrix[pivot_row] = matrix[pivot_row], matrix[step]
            logs.append(format_matrix_to_str(matrix, f"R{step+1} ↔ R{pivot_row+1}"))

        # 2. Нормализация (Pivot to 1)
        pivot_val = matrix[step][col_idx]
        if pivot_val != Fraction(1):
            for c in range(len(matrix[0])):
                matrix[step][c] = matrix[step][c] / pivot_val
            logs.append(format_matrix_to_str(matrix, f"R{step+1} = R{step+1} / ({pivot_val})"))

        # 3. Элиминация (Zeroing column)
        for r in range(m):
            if r != step:
                factor = matrix[r][col_idx]
                if factor.num != 0:
                    for c in range(len(matrix[0])):
                        matrix[r][c] = matrix[r][c] - (factor * matrix[step][c])
                    # Красивая запись: R2 = R2 - (3/2)*R1
                    logs.append(format_matrix_to_str(matrix, f"R{r+1} = R{r+1} - ({factor}) * R{step+1}"))
    
    # Проверка на совместность
    for r in range(len(basis_indices), m):
        if matrix[r][n_vars].num != 0:
            return None, [f"❌ Противоречие в R{r+1}: 0 = {matrix[r][n_vars]}"]

    solution = [Fraction(0)] * n_vars
    for i, col_idx in enumerate(basis_indices):
        solution[col_idx] = matrix[i][n_vars]
    
    return solution, logs

# --- Бот ---
load_dotenv()
TOKEN = os.getenv("TOKEN")
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

async def set_bot_commands(bot: Bot):
    custom_commands = [
        types.BotCommand(command="start", description="Начать заново")
    ]
    await bot.set_my_commands(commands=custom_commands)

kb_choice = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="Найти все решения")]],
    resize_keyboard=True
)

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await state.set_state(MatrixStates.waiting_for_matrix)
    await message.answer(
        "Пришли мне расширенную матрицу системы.\n"
        "Формат:\n"
        "<blockquote>1 2 3 4\n5 6 7 8\n9 0 1 2</blockquote>",
        reply_markup=ReplyKeyboardRemove()
    )

@dp.message(MatrixStates.waiting_for_matrix)
async def handle_matrix(message: types.Message, state: FSMContext):
    try:
        lines = message.text.strip().split('\n')
        raw_matrix = []
        for line in lines:
            row = [int(x) for x in line.replace('-', ' -').split() if x.strip()]
            if row: raw_matrix.append(row)
        
        await state.update_data(matrix=raw_matrix)
        matrix = [[Fraction(x) for x in row] for row in raw_matrix]
        rank = compute_rank(matrix)
        n_vars = len(matrix[0]) - 1
        
        await state.update_data(rank=rank, n_vars=n_vars)
        await state.set_state(MatrixStates.waiting_for_basis)
        
        await message.answer(
            f"Матрица получена! Ранг: <b>{rank}</b>.\n\n"
            f"Введи {rank} номера базисных переменных.\n"
            "Формат:\n"
            "<blockquote>Для нахождения базиса (x1, x2, x4) нужно отправить 1 2 4</blockquote>",
            reply_markup=kb_choice
        )
    except Exception as e:
        await message.answer("Ошибка в формате матрицы. Пришли только целые числа.")

@dp.message(MatrixStates.waiting_for_basis)
async def handle_basis_choice(message: types.Message, state: FSMContext):
    data = await state.get_data()
    raw_matrix = data.get("matrix")
    matrix = [[Fraction(x) for x in row] for row in raw_matrix]
    rank = data.get("rank")
    n_vars = data.get("n_vars")

    if message.text == "Найти все решения":
        all_combs = list(combinations(range(n_vars), rank))
        await message.answer(f"Проверяю {len(all_combs)} комбинаций...")
        
        found_count = 0
        for combo in all_combs:
            sol, _ = get_basic_solution_log(matrix, combo)
            if sol:
                found_count += 1
                basis_names = ", ".join([f"x{i+1}" for i in combo])
                res_text = ", ".join([f"x{i+1}=<b>{sol[i]}</b>" for i in range(n_vars)])
                await message.answer(f"✅ Базис ({basis_names}):\n{res_text}")
        
        await message.answer(f"🏁 Итого найдено: {found_count}")
        
    else:
        try:
            chosen_indices = [int(x) - 1 for x in message.text.split()]
            if len(chosen_indices) != rank:
                await message.answer(f"Нужно выбрать ровно {rank} переменных!")
                return

            sol, logs = get_basic_solution_log(matrix, chosen_indices)
            basis_names = ", ".join([f"x{i+1}" for i in chosen_indices])
            
            if sol:
                await message.answer(f"<b>🔍 Решение для базиса ({basis_names}):</b>")
                
                # Отправляем логи. Если они слишком длинные, Telegram их не примет, 
                # поэтому объединяем аккуратно.
                current_msg = ""
                for log in logs:
                    if len(current_msg) + len(log) > 3800:
                        await message.answer(current_msg)
                        current_msg = ""
                    current_msg += log + "\n"
                
                if current_msg:
                    await message.answer(current_msg)

                res_text = f"<b>✅ Итог:</b>\n" + ", ".join([f"x{i+1}=<b>{sol[i]}</b>" for i in range(n_vars)])
                await message.answer(res_text)
            else:
                await message.answer(f"❌ Набор ({basis_names}) не базис: {logs[-1]}")
        except Exception:
            await message.answer("Введи индексы через пробел.")

async def main():
    logging.basicConfig(level=logging.INFO)
    await set_bot_commands(bot)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())