# GitHub Copilot Instructions

## Multilingual UI — mandatory rule

Every user-visible string **must** be translated into all supported languages.  
Supported language codes: `de`, `en`, `fr`, `es`, `zh`, `pt`, `pl`, `it`

This applies to:
- Button labels
- LabelFrame / frame titles
- Dialog titles and body text (`messagebox.showinfo`, `messagebox.askyesno`, etc.)
- Tooltip / hint labels
- Status messages
- Any other text that appears in the UI

### How to add a new string

1. Add a key to **every** language block in `ui/translations.py`.
2. Reference it in code via the `tr` dict (obtained from `TRANSLATIONS.get(lang, TRANSLATIONS["de"])`).
3. **Never** hard-code a raw German (or any other language) string directly in widget constructors or `messagebox` calls — always go through the translation dict.

### Example

```python
# translations.py — add to ALL 8 language blocks
"my_new_key": "Mein Text",          # de
"my_new_key": "My text",            # en
# … fr, es, zh, pt, pl, it

# settings_window.py — use tr[...]
ttk.Button(frm, text=tr["my_new_key"])
messagebox.showinfo(tr["my_new_key"], tr["my_new_key_body"], parent=win)
```
