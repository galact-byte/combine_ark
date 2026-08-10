from tkinter import Tk

import pytest


@pytest.fixture(scope="session")
def root():
    value = Tk()
    value.withdraw()
    yield value
    value.destroy()
