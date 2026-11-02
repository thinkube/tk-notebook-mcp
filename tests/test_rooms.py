from jupyter_ydoc import YNotebook

from tk_notebook_mcp.tools.rooms import set_cell_outputs


def notebook_with_one_cell() -> YNotebook:
    notebook = YNotebook()
    notebook.set(
        {
            "cells": [{"cell_type": "code", "source": "", "metadata": {}, "outputs": [], "execution_count": None}],
            "metadata": {},
            "nbformat": 4,
            "nbformat_minor": 5,
        }
    )
    notebook.undo_manager.clear()
    return notebook


def test_a_runs_outputs_stay_out_of_the_undo_history():
    notebook = notebook_with_one_cell()
    text = ""
    for _ in range(200):
        text += "x" * 1000
        set_cell_outputs(notebook, 0, None, [{"output_type": "stream", "name": "stdout", "text": text}], running=True)
    set_cell_outputs(notebook, 0, 1, [{"output_type": "stream", "name": "stdout", "text": text}])

    assert len(notebook.undo_manager.undo_stack) == 0
    assert notebook.ycells[0]["outputs"][0]["text"] == text
    assert notebook.ycells[0]["execution_count"] == 1


def test_the_document_holds_one_copy_of_a_replaced_output():
    notebook = notebook_with_one_cell()
    text = ""
    for _ in range(200):
        text += "x" * 1000
        set_cell_outputs(notebook, 0, None, [{"output_type": "stream", "name": "stdout", "text": text}], running=True)

    # 200 copies of the growing text would be about 20 MB; the last one is 200 kB
    assert len(notebook.ydoc.get_update()) < 2 * len(text)
