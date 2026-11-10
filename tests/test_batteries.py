"""Обёртка для unittest: каждая батарея tests/battery_*.py — один тест (в своём процессе).

       python -m unittest tests.test_batteries -v

   При провале в сообщении перечислены непрошедшие проверки с описаниями."""

import unittest

from tests.run_all import find_batteries, run_battery


class Batteries(unittest.TestCase):
    pass


def _make_test(path):
    def test(self):
        result = run_battery(path)
        message = '\n'.join(result['fail_lines']) or result['tail'] or 'батарея не вывела итоговую строку'
        self.assertTrue(result['ok'], f"{result['name']}: проверок {result['checks']}, провалено {result['failed']}\n{message}")
    return test


for _path in find_batteries():
    _name = 'test_' + _path.replace('\\', '/').rsplit('/battery_', 1)[1][:-3]
    setattr(Batteries, _name, _make_test(_path))


if __name__ == '__main__':
    unittest.main()
