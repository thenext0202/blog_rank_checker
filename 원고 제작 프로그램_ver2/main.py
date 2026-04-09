"""원고 작성기 — 진입점"""
import tkinter as tk
from gui import ManuscriptWriterApp


def main():
    root = tk.Tk()
    ManuscriptWriterApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
