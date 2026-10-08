# -*- coding: utf-8 -*-
"""一次性 QThread 安全启动助手。

问题背景：QThread 对象若在发信号的工作线程尚未完全结束时被销毁
（例如槽函数里 `self._x = None` 丢掉最后引用，或方法返回后局部变量被 GC），
会造成 use-after-free，随机触发 0xC0000005 崩溃。

用法：把 `thread.start()` 换成 `start_worker(thread, parent=self)`。
线程结束后由 Qt 通过 deleteLater 在安全的时机回收，调用方代码不变。
"""

from PyQt5.QtCore import QObject


def start_worker(thread, parent=None):
    if parent is not None:
        thread.setParent(parent)
    thread.finished.connect(thread.deleteLater)
    thread.start()
