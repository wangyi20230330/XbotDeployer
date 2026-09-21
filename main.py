"""
Xbot Deployer 影刀应用一键迁移与部署工具
主入口文件
"""
import sys
import os


def _force_utf8_console():
    """把 stdout/stderr 切到 UTF-8（带 replace 兜底）。

    背景：程序会打印 emoji（📦/✅/❌），而中文 Windows 控制台默认 GBK，
    直接 print 会抛 UnicodeEncodeError（打包成 exe 后必现，CLI 直接崩）。
    这里在入口统一改编码；没有控制台（pythonw/无 stdout）时静默跳过。
    """
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        try:
            if stream is not None and hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


_force_utf8_console()

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    if len(sys.argv) > 1:
        from cli import run_cli
        run_cli()
    else:
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtGui import QFont
        from gui.main_window import MainWindow

        app = QApplication(sys.argv)
        app.setFont(QFont("Microsoft YaHei", 9))

        window = MainWindow()
        window.show()
        sys.exit(app.exec())


if __name__ == "__main__":
    main()
