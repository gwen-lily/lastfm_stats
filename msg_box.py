import tkinter as tk
import sys
from typing import Tuple


class Confirm:

	def __init__(self):
		self.value = None
		self.root = None

	def show(self, msg: str, options: Tuple[str, str] = ('Yes', 'No')):
		self.root = tk.Tk()

		prompt = tk.Label(self.root, text=msg, anchor="w")
		b_yes = tk.Button(self.root, text=options[0], command=lambda: self.select(True))
		b_no = tk.Button(self.root, text=options[1], command=lambda: self.select(False))
		b_exit = tk.Button(self.root, text='Exit', command=lambda: sys.exit())

		prompt.pack(side="top", fill="x")
		b_yes.pack(side="left", fill="x", padx=20, pady=20)
		b_no.pack(side="left", fill="x", padx=20, pady=20)
		b_exit.pack(side="left", fill="x", padx=20, pady=20)

		self.root.mainloop()
		return self.value

	def select(self, val):
		self.value = val
		self.root.destroy()
		self.root.quit()
