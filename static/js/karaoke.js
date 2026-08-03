// Karaoke JS minimal - interfaz vacía por ahora

console.log('Karaoke script loaded');

// Socket.IO: connect and join room when room selected to receive realtime events
var __kv_socket = null;
function ensureSocket() {
	try {
		if (typeof io === 'undefined') return null;
		if (!__kv_socket) {
			__kv_socket = io();
			__kv_socket.on('connect', function(){ console.log('Karaoke socket connected'); });
			__kv_socket.on('karaoke_event', function(payload){
				try {
					console.log('karaoke_event', payload);
					if (payload && payload.action) {
						if (payload.action === 'ticket_created') {
							var t = payload.ticket || {};
							window.showToast && window.showToast('Nuevo ticket en sala ' + (t.room || '') + ': ' + (t.buyer_name || ''), 'info');
						} else if (payload.action === 'payment_confirmed') {
							var ref = payload.reference || payload.ref;
							window.showToast && window.showToast('Pago confirmado (ref ' + (ref || '') + ')', 'success');
							// if the modal is open and the ref matches currentPaymentRef, update status
							try {
								if (typeof currentPaymentRef !== 'undefined' && currentPaymentRef && ref && currentPaymentRef === ref) {
									var yapeStatus = document.getElementById('yapeStatus');
									if (yapeStatus) yapeStatus.textContent = 'Pago confirmado.';
									// try to open invoice if provided by server via separate status check
								}
							} catch (e) { console.warn(e); }
						}
					}
				} catch (e) { console.error(e); }
			});
		}
		return __kv_socket;
	} catch (e) { console.warn('ensureSocket error', e); return null; }
}

// Validación básica del formulario de boletos
document.addEventListener('DOMContentLoaded', function () {
	const form = document.getElementById('ticketForm');
	if (!form) return;

		// ensure socket and join selected room to receive realtime events for that room
		var __kv_socket_local = ensureSocket();
		var roomSelectEl = form.querySelector('[name="room_number"]');
		function joinSelectedRoom(){
			try {
				if (!__kv_socket_local) __kv_socket_local = ensureSocket();
				if (!__kv_socket_local || !roomSelectEl) return;
				var rv = roomSelectEl.value || roomSelectEl.options[roomSelectEl.selectedIndex] && roomSelectEl.options[roomSelectEl.selectedIndex].value;
				if (rv) __kv_socket_local.emit('join_room', { room: rv });
			} catch(e){ console.warn('joinSelectedRoom error', e); }
		}
		if (roomSelectEl) {
			roomSelectEl.addEventListener('change', joinSelectedRoom);
			// try join on load if value preset
			joinSelectedRoom();
		}
	form.addEventListener('submit', function (ev) {
		const name = (form.querySelector('[name="buyer_name"]').value || '').trim();
		const id = (form.querySelector('[name="buyer_id"]').value || '').trim();
		let price = parseFloat(form.querySelector('[name="price"]').value || '0');
		const room = parseInt(form.querySelector('[name="room_number"]').value || '0', 10);
		const exitTimeInput = (form.querySelector('[name="exit_time_time"]').value || '').trim();
		// combine with today's date (automatic) into hidden field 'exit_time'
		let exitTime = '';
		if (exitTimeInput) {
			const d = new Date();
			const yyyy = d.getFullYear();
			const mm = String(d.getMonth() + 1).padStart(2, '0');
			const dd = String(d.getDate()).padStart(2, '0');
			// exitTimeInput is HH:MM (24h)
			exitTime = `${yyyy}-${mm}-${dd}T${exitTimeInput}`;
			const hidden = form.querySelector('#exit_time_hidden');
			if (hidden) hidden.value = exitTime;
		}

		// collect snacks: checkboxes with class 'snack-checkbox' and qty inputs 'snack-qty'
		const snacks = [];
		document.querySelectorAll('.snack-checkbox').forEach(function(cb) {
			if (cb.checked) {
				const id = cb.value;
				const name = cb.dataset.name || '';
				const price = parseFloat(cb.dataset.price || '0') || 0;
				const qtyInput = form.querySelector('.snack-qty[data-id="' + id + '"]');
				let qty = 1;
				if (qtyInput) qty = parseInt(qtyInput.value || '1', 10);
				if (isNaN(qty) || qty <= 0) qty = 1;
				snacks.push({id: id, name: name, qty: qty, price: price});
			}
		});
		const snacksHidden = form.querySelector('#snacks_list_hidden');
		if (snacksHidden) snacksHidden.value = JSON.stringify(snacks);

		// compute snack total and update displayed/final price
		let snackTotal = 0;
		for (let it of snacks) {
			snackTotal += (parseFloat(it.price) || 0) * (parseInt(it.qty, 10) || 0);
		}
		// set hidden snack total
		let snackTotalHidden = form.querySelector('#snack_total_hidden');
		if (!snackTotalHidden) {
			const h = document.createElement('input');
			h.type = 'hidden'; h.id = 'snack_total_hidden'; h.name = 'snack_total';
			form.appendChild(h);
			snackTotalHidden = h;
		}
		snackTotalHidden.value = snackTotal.toFixed(2);

		// update price input to include snacks (show final price to user)
		const priceInput = form.querySelector('[name="price"]');
		if (priceInput) {
			let base = parseFloat(priceInput.value || '0') || 0;
			priceInput.value = (base + snackTotal).toFixed(2);
			// recalculate the `price` variable used in validation to include snacks
			price = parseFloat(priceInput.value || '0') || 0;
		}
		if (!name || !id) {
			ev.preventDefault();
			alert('Ingrese nombre e ID.');
			return;
		}
		if (isNaN(price) || price <= 0) {
			ev.preventDefault();
			alert('Precio inválido.');
			return;
		}
		if (![1, 2].includes(room)) {
			ev.preventDefault();
			alert('Seleccione la sala 1 o 2.');
			return;
		}
		// No forzamos el bloqueo si el campo oculto `exit_time` no fue rellenado.
		// El servidor intentará usar `exit_time_time` si está presente o aceptar
		// una salida vacía. Esto evita que fallos en la carga del JS impidan
		// enviar el formulario.

		// if any snack checkbox checked, ensure qtys are valid
		if (snacks.length > 0) {
			for (let it of snacks) {
				if (!it.qty || it.qty < 1) {
					ev.preventDefault();
					alert('Introduce una cantidad válida para los snacks seleccionados.');
					return;
				}
			}
		}
	});

	// Yape QR: abrir modal y generar QR
	var yapeBtn = document.getElementById('yapeBtn');
	var genBtn = document.getElementById('genYapeQr');
	var yapeAmount = document.getElementById('yapeAmount');
	var yapeQr = document.getElementById('yapeQr');
	var yapeModalEl = document.getElementById('yapeModal');
	var checkYape = document.getElementById('checkYape');
	var yapeControls = document.getElementById('yapeControls');
	var yapeInvoiceLink = document.getElementById('yapeInvoiceLink');
	var currentPaymentRef = null;
	var _yape_local_tried_jpeg = false;
	var yapeQrPersistent = document.getElementById('yapeQrPersistent');
	var _yape_persist_timer = null;
	var yapeStatus = document.getElementById('yapeStatus');
	var _yape_payment_poll_id = null;
	var _yape_poll_attempts = 0;
	var _yape_poll_max_attempts = 24; // 24*5s = 2 minutes
	var _yape_poll_interval_ms = 5000;

	function startPaymentPolling(ref) {
		if (!ref) return;
		stopPaymentPolling();
		_yape_poll_attempts = 0;
		_yape_payment_poll_id = setInterval(function(){
			_yape_poll_attempts += 1;
			console.log('Polling payment', ref, 'attempt', _yape_poll_attempts);
			fetch('/api/payments/status', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ reference: ref }) })
			.then(function(r){ return r.json(); }).then(function(res){
				if (res && (res.success || res.status === 'paid' || res.paid)) {
					console.log('Payment confirmed by poll', ref);
					stopPaymentPolling();
					if (res.invoice_url) {
						if (yapeInvoiceLink) { yapeInvoiceLink.href = res.invoice_url; yapeInvoiceLink.style.display = 'inline'; }
						try { window.open(res.invoice_url, '_blank'); } catch(e){ console.warn('No se pudo abrir la factura automáticamente', e); }
					}
				}
			}).catch(function(err){ console.error('Polling error', err); });
			if (_yape_poll_attempts >= _yape_poll_max_attempts) { stopPaymentPolling(); console.warn('Payment polling timed out for', ref); }
		}, _yape_poll_interval_ms);
	}

	function stopPaymentPolling(){
		if (_yape_payment_poll_id) { clearInterval(_yape_payment_poll_id); _yape_payment_poll_id = null; }
		_yape_poll_attempts = 0;
	}

	// Helper: intentar mostrar imagen local (png -> jpeg). No ocultar la imagen
	// automáticamente para evitar parpadeos; sólo mostrar alerta si ninguna existe.
	function tryShowLocalYape() {
		if (!yapeQr) return;
		var localPng = '/static/img/yape_qr.png';
		var localJpeg = '/static/img/yape_qr.jpeg';
		_yape_local_tried_jpeg = false;
		yapeQr.onload = function(){
			console.log('yapeQr loaded:', yapeQr.src);
			yapeQr.style.display = 'block';
		};
		yapeQr.onerror = function(){
			console.warn('yapeQr error loading:', yapeQr.src);
			if (!_yape_local_tried_jpeg) {
				_yape_local_tried_jpeg = true;
				yapeQr.src = localJpeg; // intentar jpeg
				return;
			}
			// Ambos fallaron: no forzamos ocultado aquí para evitar parpadeos causados por re-asignaciones.
			console.warn('No se encontró imagen local de Yape en ' + localPng + ' ni ' + localJpeg);
		};
		yapeQr.src = localPng;
		// no forzamos hide; el onload mostrará la imagen cuando esté lista
	}

	function showPersistentYape(src) {
		if (!yapeQrPersistent) return;
		try {
			yapeQrPersistent.src = src || '';
			yapeQrPersistent.style.display = 'block';
			// refuerzo durante 2s para evitar que algún otro handler lo oculte
			if (_yape_persist_timer) clearInterval(_yape_persist_timer);
			var ticks = 0;
			_yape_persist_timer = setInterval(function(){
				try { yapeQrPersistent.style.display = 'block'; } catch(e){}
				ticks += 1; if (ticks > 10) { clearInterval(_yape_persist_timer); _yape_persist_timer = null; }
			}, 200);
		} catch(e){ console.warn('showPersistentYape error', e); }
	}

	function hidePersistentYape(){
		if (!yapeQrPersistent) return;
		try { yapeQrPersistent.style.display = 'none'; } catch(e){}
		if (_yape_persist_timer) { clearInterval(_yape_persist_timer); _yape_persist_timer = null; }
	}
	if (yapeBtn && yapeModalEl) {
		var yapeModal = new bootstrap.Modal(yapeModalEl);
		yapeBtn.addEventListener('click', function(){ yapeModal.show(); });
	}
	if (genBtn && yapeAmount && yapeQr) {
		genBtn.addEventListener('click', function(){
				if (typeof yapeModal !== 'undefined' && yapeModal) yapeModal.show();
				// Mostrar imagen local inmediatamente como feedback visual
				tryShowLocalYape();
				// y también en el elemento persistente
				showPersistentYape('/static/img/yape_qr.png');
				if (yapeControls) yapeControls.style.display = 'block';
				var amount = parseFloat(yapeAmount.value || '0') || 0;
			if (amount <= 0) { alert('Introduce un monto válido.'); return; }
			// Primero crear ticket vía API con los datos del formulario
			var form = document.getElementById('ticketForm');
			if (!form) { alert('Formulario no disponible'); return; }
			// calcular snacks aquí (similar al submit handler)
			var snacks = [];
			var snackTotalLocal = 0;
			document.querySelectorAll('.snack-checkbox').forEach(function(cb) {
				if (cb.checked) {
					var sid = cb.value;
					var sname = cb.dataset.name || '';
					var sprice = parseFloat(cb.dataset.price || '0') || 0;
					var qtyInput = form.querySelector('.snack-qty[data-id="' + sid + '"]');
					var sqty = 1;
					if (qtyInput) sqty = parseInt(qtyInput.value || '1', 10);
					if (isNaN(sqty) || sqty <= 0) sqty = 1;
					snacks.push({id: sid, name: sname, qty: sqty, price: sprice});
					snackTotalLocal += (sprice || 0) * (sqty || 0);
				}
			});
			var snacks_list_payload = snacks.length ? JSON.stringify(snacks) : null;
			// ensure hidden field updated for consistency
			var snacksHiddenEl = document.querySelector('#snacks_list_hidden');
			if (snacksHiddenEl) snacksHiddenEl.value = snacks_list_payload || '';

			// determine base price (prefer user input; fallback to input.defaultValue)
			var priceInputEl = form.querySelector('[name="price"]');
			var basePrice = 0;
			if (priceInputEl) {
				basePrice = parseFloat(priceInputEl.value || '') || parseFloat(priceInputEl.defaultValue || '') || 0;
			}
			var formData = {
				buyer_name: (form.querySelector('[name="buyer_name"]').value || '').trim(),
				buyer_id: (form.querySelector('[name="buyer_id"]').value || '').trim(),
				buyer_phone: (form.querySelector('[name="buyer_phone"]').value || '').trim(),
				room_number: form.querySelector('[name="room_number"]').value || '',
				exit_time: form.querySelector('#exit_time_hidden') ? form.querySelector('#exit_time_hidden').value : (form.querySelector('[name="exit_time_time"]') ? form.querySelector('[name="exit_time_time"]').value : ''),
				// send base price (without snacks) and let server add snack_total to avoid double-counting
				price: parseFloat(basePrice) || 0,
				snacks_list: snacks_list_payload
			};
			fetch('/api/tickets/create', {
				method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(formData)
			}).then(function(r){ return r.json(); }).then(function(ticketResp){
				if (!ticketResp || ticketResp.error) { alert('Error creando ticket: ' + (ticketResp && ticketResp.error)); return; }
				var ticketId = ticketResp.ticket_id;
				var amountToPay = ticketResp.price || amount;
				// si el servidor devolvió el precio final, actualizar el input del modal para mostrarlo
				try { if (amountToPay && yapeAmount) yapeAmount.value = (parseFloat(amountToPay) || 0).toFixed(2); } catch(e){}
				// Ahora crear el pago asociado al ticket
				fetch('/api/payments/create', {
					method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ amount: amountToPay, buyer: formData.buyer_name, ticket_id: ticketId })
				}).then(function(resp){ return resp.json(); }).then(function(data){
					if (data) {
						currentPaymentRef = data.reference || data.ref || null;
						if (yapeControls) yapeControls.style.display = 'block';
						if (yapeInvoiceLink) { yapeInvoiceLink.style.display = 'none'; yapeInvoiceLink.href = '#'; }
						var ref = currentPaymentRef; var wrap = document.getElementById('yapeQrWrap');
						// Prefer server-provided qr_url; si no, mostramos imagen local `static/img/yape_qr.png`
						if (data.qr_url) {
							yapeQr.src = data.qr_url; yapeQr.style.display = 'block';
							var canvasWrap = document.getElementById('yapeQrCanvas'); if (canvasWrap) canvasWrap.style.display = 'none';
						} else {
							// Intentar mostrar imagen local: png -> jpeg
							var localPng = '/static/img/yape_qr.png';
							var localJpeg = '/static/img/yape_qr.jpeg';
							yapeQr.style.display = 'block';
							yapeQr.onerror = function(){
								// si png falla, probar jpeg
								if (yapeQr.src.indexOf('.png') !== -1) {
									yapeQr.src = localJpeg; return;
								}
								// si jpeg también falla, no ocultar para evitar parpadeos; avisar en consola
								console.warn('No se encontró la imagen local del QR. Sube yape_qr.png o yape_qr.jpeg en /static/img/');
							};
							yapeQr.src = localPng;
							var canvasWrap = document.getElementById('yapeQrCanvas'); if (canvasWrap) canvasWrap.style.display = 'none';
						}
						// iniciar polling automático para confirmar el pago
						if (currentPaymentRef) startPaymentPolling(currentPaymentRef);
						if (ref && wrap) {
							var el = document.getElementById('yapeRef');
							if (!el) { el = document.createElement('div'); el.id = 'yapeRef'; el.className = 'small mt-2 text-muted'; wrap.appendChild(el); }
							el.textContent = 'Referencia: ' + ref + ' (úsala para confirmar el pago)';
						}
					} else { alert('Error al crear pago'); }
				}).catch(function(err){ console.error(err); alert('Error al crear pago'); });
			}).catch(function(err){ console.error(err); alert('Error al crear ticket'); });
		});

		// Cuando el modal se cierre, ocultamos la imagen persistente
		if (yapeModalEl && yapeModalEl.addEventListener) {
			yapeModalEl.addEventListener('hidden.bs.modal', function(){ hidePersistentYape(); });
		}
		// Verificar pago (botón) — solicita al backend confirmar el pago y muestra factura si existe
		if (checkYape) {
			checkYape.addEventListener('click', function(){
				console.log('checkYape clicked, ref=', currentPaymentRef);
				if (!currentPaymentRef) { if (yapeStatus) yapeStatus.textContent = 'No hay referencia para verificar.'; alert('No hay referencia de pago para verificar.'); return; }
				if (yapeStatus) yapeStatus.textContent = 'Verificando...';
				checkYape.disabled = true;
				fetch('/api/payments/status', {
					method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ reference: currentPaymentRef })
				}).then(function(r){
					return r.json().then(function(json){ return { ok: r.ok, json: json }; });
				}).then(function(result){
					var res = result.json;
					console.log('status result', result);
					if (res && (res.status === 'paid' || res.paid)) {
						if (yapeStatus) yapeStatus.textContent = 'Pago confirmado.';
						if (res.invoice_url) {
							if (yapeInvoiceLink) { yapeInvoiceLink.href = res.invoice_url; yapeInvoiceLink.style.display = 'inline'; }
							try { window.open(res.invoice_url, '_blank'); } catch(e){ console.warn('No se pudo abrir la factura automáticamente', e); }
						}
						// stop polling if any
						stopPaymentPolling();
					} else {
						if (yapeStatus) yapeStatus.textContent = 'Pago pendiente.';
						alert('Pago no confirmado: ' + (res && res.error ? res.error : 'pendiente'));
					}
				}).catch(function(err){ console.error(err); if (yapeStatus) yapeStatus.textContent = 'Error verificando pago.'; alert('Error verificando pago'); })
				.finally(function(){ checkYape.disabled = false; });
			});
		}

		// Botón: marcar pago como pagado (requiere sesión admin o webhook secret en servidor)
		var markPaidBtn = document.getElementById('markPaidBtn');
		if (markPaidBtn) {
			markPaidBtn.addEventListener('click', function(){
				if (!currentPaymentRef) { alert('No hay referencia para marcar.'); return; }
				if (!confirm('Marcar la referencia ' + currentPaymentRef + ' como PAGADA?')) return;
				markPaidBtn.disabled = true;
				fetch('/api/payments/confirm', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ reference: currentPaymentRef }) })
				.then(function(r){ return r.json(); }).then(function(res){
					console.log('markPaid res', res);
					if (res && (res.ok || res.reference)) {
						if (yapeStatus) yapeStatus.textContent = 'Pago marcado como pagado.';
						if (res.invoice_url) {
							if (yapeInvoiceLink) { yapeInvoiceLink.href = res.invoice_url; yapeInvoiceLink.style.display = 'inline'; }
							try { window.open(res.invoice_url, '_blank'); } catch(e){}
						}
					} else if (res && res.error) {
						alert('No autorizado o error: ' + res.error);
						if (yapeStatus) yapeStatus.textContent = 'Error: ' + res.error;
					} else {
						alert('Respuesta inesperada al marcar pago.');
					}
				}).catch(function(err){ console.error(err); alert('Error marcando pago'); }).finally(function(){ markPaidBtn.disabled = false; });
			});
		}
	}
});

