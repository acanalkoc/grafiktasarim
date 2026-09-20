# Windows kurulumu — v7.2.0

Windows 10/11 x64 için hazırlanır. Kullanıcının Python kurmasına veya uygulamayı
kullanırken internet bağlantısına ihtiyacı yoktur.

1. [Releases](https://github.com/acanalkoc/grafiktasarim/releases) sayfasındaki
   `ScientificGraphStudio-7.2.0-Windows-x64-Setup.exe` dosyasını indirin.
2. Normal kullanıcı olarak kurun; yönetici yetkisi gerekmez.
3. Başlat menüsünden **Scientific Graph Studio** uygulamasını açın.
4. **Veri Yükle → Grafik Kurulumu → Yayın** akışını kullanın.

Kurulumsuz kullanım: Portable ZIP dosyasının **tamamını** çıkartın,
klasör içindeki `ScientificGraphStudio.exe` dosyasını çalıştırın.
EXE dosyasını `_internal` klasöründen ayırmayın.

## Veri ve güncelleme güvenliği

- Otomatik kayıt: `%LOCALAPPDATA%\ScientificGraphStudio\autosave.gpj`.
- Hata günlüğü: aynı klasörde `application.log` (döngüsel, boyutu sınırlı).
- Projeleri istediğiniz klasöre `.gpj` olarak kaydedebilirsiniz.
- Yeni kurulum aynı uygulamayı günceller; projeler ve otomatik kayıtlar silinmez.
- Kaldırma işlemi kullanıcı proje/otomatik kayıt dosyalarını silmez.
- Kurulum dosyası henüz dijital olarak imzalanmıyor; Windows SmartScreen
  yayımlayıcıyı doğrulayamayabilir. Güvenlik korumalarını kapatmayın.
  Yalnızca bu deponun Release dosyalarını kullanın ve SHA256 değerini kontrol edin.
- Windows ARM ve farklı ekran ölçekleri için insan doğrulaması ayrıca gereklidir.

## Tekrar üretilebilir derleme

Windows x64 üzerinde Python 3.12 (Tk dahil) ve resmi Inno Setup 6 gereklidir:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-windows.txt
.\scripts\build_windows.ps1
```

Çıktılar `release/` altında oluşur. GitHub Actions aynı işlemi Windows üzerinde
yürütür, kaynak testlerini çalıştırır, paketlenmiş EXE'yi başlatır, sessiz kurulum
sonrasında kurulu uygulamayı yeniden test eder ve SHA256 üretir.
`v7.2.0` etiketi yalnızca başarılı adımlardan sonra Release yayımlar.
`main` gönderimleri indirilebilir Actions artifact üretir, Release yayımlamaz.

Derleme kaynakları:
[PyInstaller platforma özgü paketleme](https://pyinstaller.org/en/stable/operating-mode.html),
[Inno Setup normal kullanıcı kurulumu](https://jrsoftware.org/ishelp/topic_setup_privilegesrequired.htm).
