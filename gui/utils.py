import functools
import traceback
from tkinter import messagebox

def safe_execute(func):
    """
    GUI olaylarında meydana gelen hataları yakalayıp
    uygulamanın kapanmasını engelleyen dekoratör.
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            # Sadece hata mesajı göster, programı çökertme
            error_msg = f"Bir hata oluştu:\n{str(e)}\n\nLütfen detaylar için konsola bakın."
            try:
                # Ebeveyn penceresi (master/parent) için args[0]'ın tkinter widget'ı olup olmadığını kontrol et
                parent = args[0] if args and hasattr(args[0], 'winfo_toplevel') else None
                messagebox.showerror("Beklenmeyen Hata", error_msg, parent=parent)
            except:
                # Fallback: parent parametresi olmadan messagebox aç
                messagebox.showerror("Beklenmeyen Hata", error_msg)
            print(f"Hata detayı [{func.__name__}]:")
            traceback.print_exc()
    return wrapper
