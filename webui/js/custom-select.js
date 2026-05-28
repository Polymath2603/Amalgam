
export function initCustomSelects() {
    document.querySelectorAll('select').forEach(sel => {
        if (sel.dataset.custom) return;
        sel.dataset.custom = 'true';
        sel.style.display = 'none';

        const wrapper = document.createElement('div');
        wrapper.className = 'custom-select';
        wrapper.tabIndex = 0;

        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'custom-select-btn';
        btn.textContent = sel.options[sel.selectedIndex]?.text || sel.options[0]?.text || 'Select...';

        const list = document.createElement('div');
        list.className = 'custom-select-list';

        function buildOptions() {
            list.innerHTML = '';
            [...sel.options].forEach((opt, i) => {
                const item = document.createElement('div');
                item.className = 'custom-select-item' + (i === sel.selectedIndex ? ' selected' : '');
                item.textContent = opt.text;
                item.dataset.value = opt.value;
                item.addEventListener('click', () => {
                    sel.selectedIndex = i;
                    btn.textContent = opt.text;
                    list.querySelectorAll('.selected').forEach(s => s.classList.remove('selected'));
                    item.classList.add('selected');
                    close();
                    sel.dispatchEvent(new Event('change', { bubbles: true }));
                });
                list.appendChild(item);
            });
        }

        function open() {
            buildOptions();
            wrapper.classList.add('open');
            const rect = wrapper.getBoundingClientRect();
            list.style.minWidth = rect.width + 'px';
        }

        function close() {
            wrapper.classList.remove('open');
        }

        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            wrapper.classList.contains('open') ? close() : open();
        });

        wrapper.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); wrapper.classList.contains('open') ? close() : open(); }
            if (e.key === 'Escape') close();
        });

        document.addEventListener('click', (e) => {
            if (!wrapper.contains(e.target)) close();
        });

        wrapper.appendChild(btn);
        wrapper.appendChild(list);
        sel.parentNode.insertBefore(wrapper, sel);

        Object.defineProperty(sel, '_customBtn', { value: btn });
    });
}


export function syncCustomSelect(sel) {
    if (sel._customBtn) {
        sel._customBtn.textContent = sel.options[sel.selectedIndex]?.text || '';
    }
}

export function syncAllCustomSelects() {
    document.querySelectorAll('select[data-custom]').forEach(syncCustomSelect);
}
