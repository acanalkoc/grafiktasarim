# v7.1 tek ajanlı kullanılabilirlik ve güvenlik denetimi

20 Eylül 2026. Önceki raporlar doğruluk kanıtı kabul edilmedi. Kod ve gerçek
Tk testleri incelendi; başlangıç 199/199 PASS. Çoklu ajan/Claude çağrısı yok.

## Öncelik ve kabul

P1 veri kaybı / bilimsel yanlışlık; P2 sık kullanılan akış / erişilebilirlik;
P3 bakım ve görünüm. Geçersiz giriş tam reddedilmeli, tablo değişikliği tek
geri alma adımı olmalı, silinen kaynak asla başka sütuna/indekse bağlanmamalı.
Menü/kısayol/sağ tık aynı dışa aktarma komutuna gitmeli. Filtre veriyi silmemeli.
Mevcut testler + yeni regresyonlar + üç gerçek pencere görüntüsü doğrulanacak.

## Bulgular (ilk doğrudan inceleme; sonuçları aşağıda)

| ID / önem | Konum | Yeniden üretme | Etki / çözüm |
|---|---|---|---|
| D01 P1 | gui/data_manager.py:_on_edited | Bağımsız tabloda hücre değiştir, Undo | Hücre değişikliği kaydedilmiyor; tek checkpoint ve görünüm eşitleme |
| D02 P1 | gui/widgets.py:paste_selection | İki sütunlu tabloya üç sütun yapıştır | Son sütun sessizce kayıp; atomik sınır kontrolü, açık hata |
| D03 P1 | gui/main_window.py:_worksheet_changed | Pasif tablonun bağlı X sütununu sil | Satır indeksi X yerine geçiyor; UUID kaybında stale, çizimden dışla |
| D04 P1 | data/engine.py:_sayiya_cevir, series_from_columns | X boş/NaN/Inf iken Y sayısal | Uydurma X/sonlu olmayan değerler; açık X varsa geçersiz çiftleri atla |
| D05 P1 | gui/main_window.py:_save_to_path | Kayıt ortasında hata | Önceki dosya kesilebilir; aynı dizinde geçici dosya + atomic replace |
| D06 P1 | gui/main_window.py:_load_from_path,_restore_state | Proje aç, Undo; açık tabloda Undo sonrası düzenle | Eski proje geçmişi/görünümü karışabilir; load transaction, history reset, bütün tabloları tazele |
| D07 P1 | gui/main_window.py / analysis/provenance.py | Analizden sonra kaynak veriyi değiştir | Eski sonuç güncel görünüyor; kaynak damgası, stale yazısı, eski overlay temizliği |
| U01 P2 | export_current, PublicationDialog, NavigationToolbar | Ctrl+E ve Yayın düğmesini karşılaştır | İki ayrı boyut/doğrulama yolu; tek yayın komutu |
| U02 P2 | ScientificTable:_show_context_menu | Seçim dışına sağ tık, sil | Eski seçim siliniyor; aralık içini koru, dışını hedefle |
| U03 P2 | ScientificTable:Tab | Tab ile son sütuna ilerle | Odak tablodan çıkmıyor; uçlarda odak ilerlet, Ctrl+Tab kaçışı |
| U04 P2 | WorksheetTableWindow | Büyük tablo aç | Scrollbar, sıralama, filtre ve sütun özellikleri yok; az düğmeli İşlemler menüsü + kaydırma |
| U05 P2 | PlotSetupDialog | Geçersiz Y ile Ekle; yinelenen Ekle | Kısmi değişiklik/tür değişmesi; önce bütün adayları doğrula, no-op idempotent |
| U06 P2 | themes.py | Koyu temada mavi düğme/seçim | Beyaz üstüne açık mavi düşük kontrast; kontrastlı metin ve görünür odak |
| U07 P2 | main_window:_init_variables | Çocuk tablo penceresinde Undo | Ana pencere kısayolları çocukta çalışmıyor; ortak pencere komutları |
| U08 P2 | main_window:_build_control_widgets | Ayrıntılar aç | İçe aktarma/tür seçimi tekrar; ayrıntıları seri stiliyle sınırla |
| U09 P2 | main_window:_center_window | Küçük ekranla başlat | Sabit 1340×860 ekranı aşıyor; ekran sınırına sığdır |
| M01 P3 | gui/main_window.py | Sınıfı incele | 6222 satır, UI/state/IO birleşik; saf tablo işlemleri ve atomik persistence modülleri çıkar |

## Uygulanan sonuçlar

- D01–D06 düzeltildi. Bağımsız hücre düzenleme, sıralama ve yapıştırma geri
  alınabiliyor; Undo/Redo açık tabloları tazeliyor. Boş tabloya yapıştırma
  çalışıyor. Taşan sütunlar bütün işlem reddedilerek korunuyor. Çok satırlı
  hücreler TSV quoting ile kopyalanıp geri yapıştırılabiliyor.
- Kaydetme serialize → aynı dizinde geçici dosya → fsync → atomic replace
  kullanıyor. Disk hatasında eski dosya ve başarısız proje yüklemede mevcut
  durum korunuyor. Proje açılması geçmişi yeni belgeye sıfırlıyor. Kapatma,
  proje değiştirme ve otomatik kayıt kurtarmada kaydedilmemiş iş korunuyor.
- D07 düzeltildi: kaynağı değişen analiz arşivine “Eski/Stale” durumu yazılıyor;
  açık analiz penceresinin bekleyen sonucu geçersizleştiriliyor. Stale kaynak
  analize ve grafiğe alınmıyor. Eski indeks tabanlı fit/alan overlay'leri veri
  değişiminde muhafazakâr biçimde temizleniyor (arşiv silinmiyor).
- **Ek D08 / P1:** `_apply_analysis_signal_result`: pasif tablodan üretilmiş
  sinyal sonucunu uygula → sonuç aktif tabloya yazılıyordu. Sonuç artık kaynak
  worksheet UUID'sine ve korunmuş satır indekslerine yazılır; geçersiz satır
  eşleşmesi işlemden önce reddedilir. Bir Undo sonucu geri alır.
- **Ek D09 / P1:** hata sütunu seçimi aktif tablonun sütunlarını kullanıyordu;
  iki farklı düzenleyicide ayrı mantık vardı. `gui/errorbars.py` tek kullanıcı
  düzenleyicisi; `data/bindings.py` ortak uygulama/yenileme politikasıdır.
  Hata kaynağı UUID ile izlenir; sütun eklemede kaymaz, silmede stale olur.
  Eksik/negatif hata sıfır varsayılmaz. SD/SEM/CI anlamı kullanıcı tarafından
  seçilip proje içinde saklanır; yazılım bunları seçilen sütundan hesapladığını
  iddia etmez. Grafik genel ayarları da kayda/geri alma durumuna dahil edildi.
- **Ek D10 / P1:** `otomatik_rol_tahmin_et`, “Response”/“Dose” içindeki `se`
  alt dizisini hata sütunu sanıyordu. Açık kelime/etiket eşleştirmesi ve
  regresyon testi eklendi. Sayısal metinlerde NaN/Inf/taşma reddediliyor.
- **Ek D11 / P1:** `DataEngine.save_file`: çoğunluğu sayısal sütunda metin
  bulunan bir hücreyi Excel'e aktar → eski dönüştürme metni boşaltıyordu.
  Hücre bazlı kayıpsız dönüşüm uygulandı; gerçek XLSX yeniden açılarak test edildi.
- U01 düzeltildi: menü, kısayol, sağ tık ve Matplotlib Kaydet aynı yayın
  penceresine gider. Eski inç tabanlı ayrı exporter kaldırıldı. “Çıktı
  Önizlemesi” gerçek export renderer'ını, mm boyutunu ve font ayarlarını
  kullanır; ekran görüntüsü önizlemesi çizimi kalıcı değiştirmez.
- U02–U05 düzeltildi. Sağ tık aralık dışına gelince hedefi değiştirir,
  aralık içinde seçimi korur. Tab uçlarda çıkar; Ctrl+Tab ve Shift+F10 var.
  Tablo işlemleri görünür menüde; X/Y isimleri, roller ve birimler ortak sütun
  özelliklerinde. Filtre yalnız görünümü daraltır ve açıkça salt okunurdur;
  filtreyi temizlemeden kaynak satırlarını yanlışlıkla silmek mümkün değildir.
  Sıralama bütün satırı taşır, boşlar sonda kalır. Ekle de Değiştir gibi önce
  bütün adayları doğrular; yinelenen Ekle türü veya yerleşimi değiştirmez.
- U06–U09 iyileştirildi: koyu temadaki seçili metin/düğme kontrastı, odak
  kenarlıkları ve tıklama dolguları artırıldı. Çocuk tablolarda belge
  kısayolları var. Ayrıntılar artık içe aktarma/tür formunu tekrar etmez.
  Ana UI tablo girişleri aynı worksheet penceresine yönlenir; eski tablo
  adaptörü yalnız eski entegrasyon/test uyumluluğu için kodda tutuldu.
  Pasta/3B türleri gelişmiş menüde korunuyor. Ana pencere ekran sınırına sığar.
- **Ek U10 / P2:** küçük pencerede panel başlığı/harfi ve komşu Y ekseni
  çakışıyordu. Yeni panel yerleşiminde yatay boşluk artırıldı; harfler başlıktan
  ayrıldı. Kullanıcının mevcut özel dikdörtgenleri otomatik üzerine yazılmaz.
- **Ek U11 / P2:** macOS ilk görünürlükte hücre bbox bilgisi henüz son
  yerleşimi yansıtmıyordu; odak çizgisi başlığı çevreliyordu. Map/resize sonrası
  geciktirilmiş hizalama ile düzeltildi. Son gerçek ölçüm: bbox `(2,24,362,25)`;
  odak üst çizgisi y=24, genişlik=362. Önce y=3/genişlik=100 idi.
- Seri düzenleyici seçimi yenilemede plot UUID'siyle korunuyor. Dil değişiminde
  Plot Setup X/Y seçimi sıra numarasıyla değil UUID ile korunuyor.
- M01 kısmen düzeltildi: saf tablo işlemleri `core/editing.py`, güvenli IO
  `core/persistence.py`, kaynak yenileme `data/bindings.py` ve hata UI'sı
  `gui/errorbars.py` olarak ayrıldı. Ana sınıfın tümden parçalanması yapılmadı.

## 12 başlık üzerinden kapanış

| Başlık | Bu turdaki sonuç / kalan sınır |
|---|---|
| Tekrarlar | Yayın, hata kaynağı ve kullanıcıya açık tablo rotaları birleştirildi; global/katman eksen editörlerinin tamamı henüz tek inspector değil |
| Görsel sadelik | Stil-only ayrıntı penceresi, tablo İşlemler menüsü, geniş önizleme; küçük ekranda panel aralıkları düzeltildi |
| Keşfedilebilirlik | Tablo işlemleri ve grafik kurulumu görünür; eski Matplotlib simgeleri/tooltip yerelleştirmesi tam değil |
| Tutarlılık | Ortak sütun özellikleri/komutlar, UUID seçim koruması; eski TR/EN pencerelerin tümü canlı çevrilmiyor |
| Erişilebilirlik | Klavye kaçış/menü, odak ve kontrast; VoiceOver ve farklı fiziksel DPI monitörleriyle henüz doğrulanmadı |
| İşlem yükü | Tablo → grafik kurulumu kaynak hazır; tekrarlı export ve hata-formu kaldırıldı; otomatik çoklu Y seçimi bu tur değiştirilmedi |
| Geri bildirim | Filtre/satır sayısı, canlı veri durumu, stale metni, yayın önizlemesi; uzun görev iptali aşağıda |
| Güvenlik | Atomik kayıt/yükleme/yapıştırma, tablo undo, geçersiz stil reddi, kaynak kimlikleri |
| Temel tablo | Düzenle, aralık seç, kopyala/yapıştır, satır/sütun ekle/sil, sütun adı/rol/birim, sırala ve salt okunur filtre |
| Bilimsel doğruluk | Eksik X uydurulmaz, sonlu olmayan değerler atlanır, hata satırları hizalıdır, yanlış tabloya analiz yazılmaz; kategorik X/eksik veri politikaları aşağıda |
| Yayın | Aynı renderer ile önizleme/export, mevcut exact-mm/vector testleri, küçük-ekran panel yerleşimi; otomatik bütün metin taşmalarını tespit etme yok |
| Bakım | Dört odaklı modül ve 40 yeni regresyon; büyük main_window ve legacy adaptörler hâlâ teknik borç |

## Test ve görsel kanıt

Başlangıç: **199/199 PASS** (bu tur yeniden çalıştırıldı, 2.954 s).
Son birleşik koşu: **239/239 PASS**, sıfır atlama, 3.174 s. 40 yeni test
`test_v71_audit.py` içinde. Yalnız eski tekrarlı sidebar düğmelerini zorunlu
sayan iki UI assertion yeni tasarıma göre güncellendi; bilimsel assertion
silinmedi. Beklenen hatalı dosya testi konsola doğrulama hatası yazıyor;
eski sabit-veri SciPy testinin precision-loss uyarısı devam ediyor.

```sh
MPLCONFIGDIR=/tmp/grafik-mpl /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 -m unittest test_v63_panels test_v62_workspace test_suite test_analysis_studio test_error_bar_plots test_v70_workflow test_v71_audit -q
```

`qa_capture_v71.py` gerçek Tk pencerelerini sentetik verilerle açar. PNG'ler
Pillow verify ve ayrıca görüntü açılarak insan-benzeri görsel kontrol ile
doğrulandı; mockup veya yalnız eski ekran görüntüsü kullanılmadı.

- `screenshots/v71_01_workspace.png`: 1200×760; önizleme 744 px (%62).
- `screenshots/v71_02_table.png`: 760×480; başlık değil gerçek hücre çevresinde
  seçim çerçevesi, görünür İşlemler/Filtre/Grafik Kurulumu.
- `screenshots/v71_03_publication_preview.png`: 854×686; 183×140 mm, 300 DPI
  PDF ayarlarının aynı export renderer'ından ekran önizlemesi.
- Ek QA: hata çubuğu penceresinin bütün kontrolleri görünür.

Durum: teknik düzeltmeler/testler tamamlandı; **görsel insan kabulü bekleniyor**.

## İncelenen ama bu turda tam yeniden yazılmayan alanlar

- Eksen/ızgara/legend global-katman mirası ve Layer Manager'daki eski atama
  bölümü hâlâ kapsamlı tek-inspector birleştirmesi gerektiriyor.
- Çok büyük dosyada içe aktarma ana UI thread'inde; gerçek ilerleme/iptal,
  sanallaştırılmış tablo ve uzun analiz iptali ayrı mimari iş.
- Ekran okuyucu ve farklı monitör/DPI donanımıyla erişilebilirlik sertifikası
  verilmedi; klavye/odak/kontrast düzeltmeleri bunu ikame etmez.
- SD/SEM/CI anlamı veriden çıkarılmaz; kullanıcı kaynak belirsizliğini belirtmeli.
  Eksik değer politikası metadata seçenekleri hesaplamada tam uygulanmadığından
  desteklenmeyen seçenekler kaldırıldı; otomatik imputasyon yok.

Desteklenmeyen Zero/Interpolate seçenekleri bu tur sütun özelliklerinden
kaldırıldı. Eski dosyadaki metadata silinmez fakat hesaplanmış bir imputasyon
gibi sunulmaz. Sayısal XY akışında seçilmiş X'in metin/boş olması artık indeks
uydurmaz. Kategorik sütun için **Sütun Özellikleri → Ayrıntılar → Veri Tipi →
Categorical** seçilir; sütun grafikleri artık özgün kategori adlarını gösterir.
Hem seri üretimi hem gerçek grafikte etiketler test edildi. Bu açık seçim,
sayısal bir X sütunundaki yazım hatasını kategori sanmamak için gereklidir.
Eksik satırları atlayan çizgi mevcut geçerli noktaları bağlar; otomatik boşluk
gösterme veya interpolasyon seçimi henüz eklenmedi. Birim metadata'sı düzenlenir;
eksen etiketi biriminin bilimsel uygunluğu kullanıcı tarafından kontrol edilir.

Önerilen sıra: (1) tek global/katman inspector ve command registry; (2) büyük
tabloda sanallaştırma, iş kuyruğu ve gerçek iptal; (3) VoiceOver/DPI matrisi ve
dergiye özel otomatik taşma/renk denetimi. Bunlar bu turun tamamlandı iddiasına
dahil değildir.

## Dayanak

W3C klavye tuzağı olmaması ilkesi masaüstü etkileşimine tasarım rehberi olarak
uyarlandı; WCAG sertifikası iddiası değildir:
https://www.w3.org/WAI/WCAG22/Understanding/no-keyboard-trap.html

Matplotlib'in eksik veriyi atlama ile NaN/mask kullanarak çizgide boşluk
gösterme ayrımı: https://matplotlib.org/stable/gallery/lines_bars_and_markers/masked_demo.html
Her iki kaynak bu tur doğrudan açıldı.
