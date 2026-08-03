document.addEventListener('DOMContentLoaded', function () {
  const table = document.querySelector('table.table-striped');
  if (!table) return;

  function showAlert(container, msg, type='success'){
    const alert = document.createElement('div');
    alert.className = `alert alert-${type} py-1 mt-2`;
    alert.textContent = msg;
    container.parentElement.insertBefore(alert, container);
    setTimeout(() => alert.remove(), 3000);
  }

  table.querySelectorAll('tbody tr').forEach(row => {
    const editBtn = row.querySelector('.btn-edit-product');
    const saveBtn = row.querySelector('.btn-save-product');
    const cancelBtn = row.querySelector('.btn-cancel-product');
    const viewBtn = row.querySelector('.btn-outline-primary');
    if (!editBtn) return;

    const getCells = () => row.querySelectorAll('td');
    const prodId = row.dataset.productId;

    if (viewBtn) {
      viewBtn.addEventListener('click', () => {
        if (!prodId) return;
        fetch(`/productos/${prodId}/json`).then(r=>r.json()).then(j=>{
          if (j && j.ok && j.product){
            const p = j.product;
            document.getElementById('productViewTitle').textContent = p.name || 'Producto';
            document.getElementById('productViewImage').src = p.image || '/static/img/placeholder.svg';
            document.getElementById('productViewName').textContent = p.name || '';
            document.getElementById('productViewDesc').textContent = p.description || '';
            document.getElementById('productViewPrice').textContent = (p.price_bs||0).toFixed(2) + ' Bs';
            document.getElementById('productViewStock').textContent = 'Stock: ' + (p.stock||0);
            var modal = new bootstrap.Modal(document.getElementById('productViewModal'));
            modal.show();
          } else {
            showAlert(table, 'Producto no encontrado', 'danger');
          }
        }).catch(()=> showAlert(table, 'Error consultando producto', 'danger'));
      });
    }

    editBtn.addEventListener('click', () => {
      const cells = getCells();
      // td0: image+name -> edit name only
      const nameCell = cells[0];
      const skuCell = cells[1];
      const stockCell = cells[2];
      const priceCell = cells[3];
      const name = nameCell.querySelector('.fw-bold') ? nameCell.querySelector('.fw-bold').textContent.trim() : nameCell.textContent.trim();
      nameCell.dataset.orig = name;
      nameCell.innerHTML = '';
      const nameInput = document.createElement('input'); nameInput.type='text'; nameInput.className='form-control form-control-sm'; nameInput.value = name; nameCell.appendChild(nameInput);

      const sku = skuCell.textContent.trim(); skuCell.dataset.orig = sku; skuCell.innerHTML=''; const skuInput = document.createElement('input'); skuInput.type='text'; skuInput.className='form-control form-control-sm'; skuInput.value=sku; skuCell.appendChild(skuInput);

      const stock = stockCell.textContent.trim(); stockCell.dataset.orig = stock; stockCell.innerHTML=''; const stockInput = document.createElement('input'); stockInput.type='number'; stockInput.className='form-control form-control-sm'; stockInput.value=stock; stockCell.appendChild(stockInput);

      const price = priceCell.textContent.trim(); priceCell.dataset.orig = price; priceCell.innerHTML=''; const priceInput = document.createElement('input'); priceInput.type='number'; priceInput.step='0.01'; priceInput.className='form-control form-control-sm'; priceInput.value = price.replace('Bs','').trim() || 0; priceCell.appendChild(priceInput);

      editBtn.classList.add('d-none'); saveBtn.classList.remove('d-none'); cancelBtn.classList.remove('d-none');
    });

    cancelBtn.addEventListener('click', () => {
      const cells = getCells();
      [0,1,2,3].forEach(idx=>{
        const c = cells[idx];
        if (c && c.dataset.orig !== undefined){
          c.textContent = c.dataset.orig;
          delete c.dataset.orig;
        }
      });
      editBtn.classList.remove('d-none'); saveBtn.classList.add('d-none'); cancelBtn.classList.add('d-none');
    });

    saveBtn.addEventListener('click', () => {
      const cells = getCells();
      const name = cells[0].querySelector('input') ? cells[0].querySelector('input').value.trim() : (cells[0].textContent||'').trim();
      const sku = cells[1].querySelector('input') ? cells[1].querySelector('input').value.trim() : (cells[1].textContent||'').trim();
      const stock = cells[2].querySelector('input') ? cells[2].querySelector('input').value.trim() : (cells[2].textContent||'').trim();
      const price = cells[3].querySelector('input') ? cells[3].querySelector('input').value.trim() : (cells[3].textContent||'').trim();

      if (!prodId) { showAlert(table,'ID de producto desconocido','danger'); return; }

      const payload = { name: name, sku: sku, stock: stock, price_bs: price };
      fetch(`/productos/${prodId}/edit`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload) })
        .then(r=>r.json()).then(j=>{
          if (j && j.ok){
            // actualizar UI
            cells[0].innerHTML = `<img src="${j.product.image || '/static/img/placeholder.svg'}" alt="${j.product.name}" style="width:10mm;height:10mm;object-fit:cover;border:1px solid #ddd;padding:2px;background:#fff" /><div class="d-inline-block ms-2 align-middle"><div class="fw-bold">${j.product.name}</div>${j.product.description ? `<div class=\"small text-muted\">${j.product.description}</div>` : ''}</div>`;
            cells[1].textContent = j.product.sku || '';
            cells[2].textContent = j.product.stock || 0;
            cells[3].textContent = (j.product.price_bs||0).toFixed(2) + ' Bs';
            editBtn.classList.remove('d-none'); saveBtn.classList.add('d-none'); cancelBtn.classList.add('d-none');
            showAlert(table,'Producto actualizado');
          } else {
            showAlert(table, (j && j.error) ? j.error : 'Error actualizando', 'danger');
          }
        }).catch(()=> showAlert(table,'Error actualizando','danger'));
    });
  });
});
