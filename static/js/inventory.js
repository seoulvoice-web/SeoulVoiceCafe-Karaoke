document.addEventListener('DOMContentLoaded', function () {
  function toggleRowEditing(row, enable) {
    const inputs = row.querySelectorAll('input.form-control');
    inputs.forEach(input => {
      if (enable) {
        input.removeAttribute('readonly');
        input.classList.remove('bg-light');
      } else {
        // restore original value if canceling
        const orig = input.getAttribute('data-original-value');
        if (orig !== null) input.value = orig;
        input.setAttribute('readonly', '');
        input.classList.add('bg-light');
      }
    });
    row.querySelectorAll('.btn-edit').forEach(b => b.classList.toggle('d-none', enable));
    row.querySelectorAll('.btn-save').forEach(b => b.classList.toggle('d-none', !enable));
    row.querySelectorAll('.btn-cancel').forEach(b => b.classList.toggle('d-none', !enable));
  }

  // Use AJAX (fetch) to submit edits per row to avoid invalid form-in-table issues
  document.querySelectorAll('tr.row-editable').forEach(row => {
    const editBtn = row.querySelector('.btn-edit');
    const saveBtn = row.querySelector('.btn-save');
    const cancelBtn = row.querySelector('.btn-cancel');
    const deleteBtn = row.querySelector('.btn-delete');

    // set initial style
    row.querySelectorAll('input.form-control').forEach(i => i.classList.add('bg-light'));

    if (editBtn) {
      editBtn.addEventListener('click', () => toggleRowEditing(row, true));
    }
    if (cancelBtn) {
      cancelBtn.addEventListener('click', () => toggleRowEditing(row, false));
    }

    if (saveBtn) {
      saveBtn.addEventListener('click', async () => {
        const id = row.querySelector('input[name="edit_id"]').value;
        const name = row.querySelector('input[name="edit_name"]').value.trim();
        const price = row.querySelector('input[name="edit_price"]').value;
        const stock = row.querySelector('input[name="edit_stock"]').value;
        if (!name) { alert('El nombre no puede estar vacío'); return; }
        if (isNaN(parseFloat(price)) || parseFloat(price) < 0) { alert('Precio inválido'); return; }
        if (!Number.isInteger(Number(stock)) || Number(stock) < 0) { alert('Stock inválido'); return; }

        const form = new URLSearchParams();
        form.append('edit_id', id);
        form.append('edit_name', name);
        form.append('edit_price', price);
        form.append('edit_stock', stock);

        try {
          const res = await fetch('/inventory', { method: 'POST', body: form });
          if (res.redirected) {
            window.location.href = res.url;
            return;
          }
          // otherwise reload to reflect changes
          window.location.reload();
        } catch (err) {
          alert('Error al guardar: ' + err.message);
        }
      });
    }

    if (deleteBtn) {
      deleteBtn.addEventListener('click', async () => {
        const idToDelete = deleteBtn.getAttribute('data-delete-id');
        if (!confirm('Confirma eliminar el producto?')) return;
        const form = new URLSearchParams();
        form.append('delete_id', idToDelete);
        try {
          const res = await fetch('/inventory', { method: 'POST', body: form });
          if (res.redirected) { window.location.href = res.url; return; }
          window.location.reload();
        } catch (err) {
          alert('Error al eliminar: ' + err.message);
        }
      });
    }
  });
});
