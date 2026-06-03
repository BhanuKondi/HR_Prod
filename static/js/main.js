(() => {
    const csrfMeta = document.querySelector('meta[name="csrf-token"]');
    const csrfToken = csrfMeta ? csrfMeta.getAttribute("content") : null;

    if (!csrfToken) {
        return;
    }

    const ensureCsrfField = (form) => {
        if (!form || form.method.toUpperCase() !== "POST") {
            return;
        }
        if (form.querySelector('input[name="csrf_token"]')) {
            return;
        }
        const hidden = document.createElement("input");
        hidden.type = "hidden";
        hidden.name = "csrf_token";
        hidden.value = csrfToken;
        form.appendChild(hidden);
    };

    document.querySelectorAll("form").forEach(ensureCsrfField);

    const observer = new MutationObserver((mutations) => {
        mutations.forEach((mutation) => {
            mutation.addedNodes.forEach((node) => {
                if (!(node instanceof Element)) {
                    return;
                }
                if (node.tagName === "FORM") {
                    ensureCsrfField(node);
                }
                node.querySelectorAll?.("form").forEach(ensureCsrfField);
            });
        });
    });
    observer.observe(document.body, { childList: true, subtree: true });
})();
