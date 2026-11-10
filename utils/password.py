"""Пароль входа в программу (окно авторизации в sp.py, "Настройки → Сменить
   пароль" в ui/app_window.py).

   Паролей два, и подходит ЛЮБОЙ из них:
   - прежний — день и месяц сегодняшней даты в виде ДДММ (например, 0710 для
     7 октября): работает всегда, его не нужно ни хранить, ни настраивать;
   - сменный — задаётся в меню настроек, хранится в mconfig.ini ([Settings]
     password_hash и password_salt) только в виде соленого хеша, самого пароля в
     файле нет.

   Так сделано намеренно: если сменный пароль забыт, войти всё равно можно по
   прежнему (и заменить сменный на новый). В прежней версии программы было
   иначе — после смены пароля ДДММ переставал работать, — но здесь нужно
   именно "наравне".

   Хеш считается так же, как в прежней версии (PBKDF2-HMAC-SHA256, 100 000
   итераций, соль — 16 случайных байт в hex, сам хеш в hex), поэтому значения
   password_hash/password_salt, сохранённые прежней версией, остаются
   действительными."""

import binascii
import hashlib
import hmac
import os
from datetime import datetime

ITERATIONS = 100_000


def generate_salt() -> str:
    return binascii.hexlify(os.urandom(16)).decode('utf-8')


def hash_password(password: str, salt: str) -> str:
    key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), ITERATIONS)
    return binascii.hexlify(key).decode('utf-8')


def make_password_record(new_password: str):
    """(hash, salt) для сохранения в конфигурации. Соль каждый раз новая."""
    salt = generate_salt()
    return hash_password(new_password, salt), salt


def date_password(now=None) -> str:
    """Прежний пароль: день и месяц, по две цифры (ДДММ)."""
    now = now or datetime.now()
    return f"{now.day:02d}{now.month:02d}"


def check_password(plain: str, stored_hash: str = '', salt: str = '', now=None) -> bool:
    """True, если plain совпадает с ПРЕЖНИМ паролем (ДДММ) ИЛИ со сменным
       (хеш и соль из конфигурации; если они не заданы — сменного пароля нет, и
       подходит только прежний). Сравнение в постоянное время."""
    plain_bytes = (plain or '').encode('utf-8')
    matches_date = hmac.compare_digest(plain_bytes, date_password(now).encode('utf-8'))
    matches_custom = False
    if stored_hash and salt:
        computed = hash_password(plain or '', salt)
        matches_custom = hmac.compare_digest(computed.encode('utf-8'), stored_hash.encode('utf-8'))
    return matches_date or matches_custom
