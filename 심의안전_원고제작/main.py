"""
심의안전 원고제작기 v1.0
심의 걸리지 않는 건강/의학 블로그 원고 자동 생성
"""
import tkinter as tk
from gui import SafetyManuscriptApp


def main():
    root = tk.Tk()
    app = SafetyManuscriptApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
