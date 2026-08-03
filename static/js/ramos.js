document.addEventListener('DOMContentLoaded', function () {
  async function postJson(url, data) {
    const resp = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    });
    return resp.json();
  }

  function showToast(msg, type='success'){
    alert(msg);
  }

  document.querySelectorAll('.btn-buy').forEach(btn=>{
    btn.addEventListener('click', async function(e){
      const id = this.dataset.id;
      const card = this.closest('.product-card');
      const qtyInput = card.querySelector('.qty-input');
      const qty = parseInt(qtyInput.value)||1;
      this.disabled = true;
      try{
        const result = await postJson(`/ramos/purchase`, { id: id, qty: qty });
        if(result.ok){
          const stockSpan = card.querySelector('.product-stock');
          stockSpan.textContent = result.new_stock;
          showToast('Compra realizada. '+result.message);
        } else {
          showToast(result.message || 'Error en la compra', 'error');
        }
      }catch(err){
        console.error(err);
        showToast('Error al procesar la compra', 'error');
      }
      this.disabled = false;
    });
  });

  document.querySelectorAll('.btn-view').forEach(btn=>{
    btn.addEventListener('click', async function(){
      const id = this.dataset.id;
      try{
        const res = await fetch(`/productos/${id}/json`);
        const p = await res.json();
        const body = `Nombre: ${p.name}\nPrecio: ${p.price_bs} Bs\nStock: ${p.stock}\n\n${p.description||''}`;
        alert(body);
      }catch(e){ console.error(e); alert('No se pudo cargar el producto'); }
    });
  });
});
