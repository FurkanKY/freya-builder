# Freya Builder — Mimari Tasarım

Tarih: 10 Ekim 2026. Durum: Revizyon 2; kullanıcı uygulamayı başlattı. Aşağıdaki revizyon kararları önceki ayrıntıların önüne geçer.

## Hedef

Bir veya birden fazla banka brief’i ve bu brief’e ait OpenAPI dosyasını okuyarak Freya üzerinde çalışan bir telefon ajanı oluşturmak; mevcut ve uygun testlerle otomatik olarak değerlendirmek; somut hatalara göre iyileştirmek; 30 dakika içinde workflow export’u ve tekrar çalıştırılabilir bir çalışma kaydı üretmek.

Builder dışarıda, Python ve Claude Agent SDK ile çalışır. Claude Code oturumu kullanılacaktır; oturumun SDK tarafından kullanılabildiği ilk çalıştırmada doğrulanacaktır. Telefon ajanının modeli kit tarafından belirlenir ve değiştirilmez.

## Doğrulanmış başlangıç durumu

- Kit v3 indirildi ve v2 ile karşılaştırıldı. Brief’ler, OpenAPI, Freya istemcisi, workflow belgeleri ve test araçları aynı; örnek builder’ın test bitmeden sonlanmasını önleyen süre ve foreground ayarları eklenmiş.
- README örnek builder için Brief A’da tek çalışmada 10/10 bildirmiştir. Bu bizim ölçümümüz değildir; üç tekrar, Brief B ve farklı konuşma biçimleri için kanıt değildir.
- Freya; extraction, routing ve dialogue işlerini ayrı yürütür. Dialogue prompt’undaki bir geçiş talimatı routing kuralı yerine geçmez.
- Python code node’ları, API araçları, ön/son hook’lar ve deterministik geçişler kullanılabilir. Sandbox’ın bütün Python modüllerini desteklediği varsayılmaz.
- `freya.save_workflow` aynı slotu günceller; güncellemenin yayımlanması test edilen sürümü etkiler. `freya.export_workflow` platformdaki workflow’u teslim biçimine dönüştürür.
- `run_cases.py` vaka seçimi, tekrar sayısı, konuşma stili ve JSON raporu destekler. Banka oturumları sunucuda vaka kimliğiyle açılır; yerel test JSON’una yeni bir müşteri eklemek sunucuda o müşteriyi yaratmaz.
- Bir workspace aynı anda bir simülasyon çalıştırır. Bir simülasyonun içindeki çağrı paralelliği bundan farklıdır; kit’in varsayılanını değiştirmeyiz.
- Hiçbir canlı Freya testi veya Claude çağrısı henüz yapılmadı.

## Başarı tanımı

1. Tek komut, insan müdahalesi olmadan verilen brief ve API şemasından ajan üretir.
2. Workflow doğrulanır, Freya’da yayımlanır ve mevcut testler gerçekten bu sürümü çalıştırır.
3. Sonuç; konuşma, araç çağrıları ve banka kayıtları üzerinden değerlendirilir. Modelin başarı beyanı puan sayılmaz.
4. Yerel hedef public A ve B’nin ayrı ayrı üç tekrarda tam geçmesidir; garanti değildir. Sonuca ulaşılamazsa gerçek skor ve açık hatalar raporlanır.
5. Gizli brief’lerde test erişimi yoksa bu açıkça yazılır; public brief’in beklenen sonuçları yeni brief’e uygulanmaz.
6. Export, seçilen aday, test sonuçları ve trace arasında sürüm bağı bulunur. En son oluşturulan aday otomatik olarak en iyi aday sayılmaz.
7. Builder tekrar çalıştırıldığında elle düzeltmeye veya önceki çalışmanın gizli verilerine ihtiyaç duymaz.

## Mimari karar

Tek Python süreci koordinatör olur. Tek Claude entegrasyonu farklı aşamalar için sınırlandırılmış oturumlar çalıştırır. İlk sürümde bağımsız ajanlar ağı, dağıtık iş kuyruğu, web paneli veya veritabanı kurulmaz. Dosyalar ve JSONL kayıtları yeterlidir.

Akış: Girdiler → politika ve araç sözleşmesi → workflow adayı → yerel/platform doğrulaması → yayımlama → test → teşhis → hedefli aday düzeltmesi → yeniden değerlendirme → seçilen sürümü yayımlama ve export.

Üç seçenek değerlendirildi:

| Seçenek | Karar |
|---|---|
| Kit’in serbest coding agent döngüsü | İlk ölçüm ve karşılaştırma sistemi olarak kullanılır. |
| Python koordinatör + yapılandırılmış model çıktıları | Hedef mimari; süre, sürüm ve kanıt kontrolü için seçildi. |
| Çok ajanlı tasarım/eleştiri/arama ağı | Başlangıç kapsamı dışında; ölçülmüş ihtiyaç olmadan eklenmez. |

Model SDK’sını baştan genelleştirilmiş bir sağlayıcı framework’üne çevirmeyiz. Küçük bir `ClaudeBackend` sınırı, gelecekte değiştirmek için yeterlidir.

## Bileşenler ve sorumluluklar

### Koordinatör

Komut satırı, çalışma kimliği, toplam süre, aşamalar, hata durumları ve teslim işlemini yönetir. Modelin kendi değerlendirmesiyle çalışmayı erken başarılı saymasını engeller. Builder kaynak kodu bir çalışma sırasında değiştirilmez; yalnızca çalışma klasöründeki adaylar değişebilir.

### Brief ve API çözümleyicisi

Tüm brief dosyalarını sırasıyla alır fakat dosya sırasını tek başına otorite sırası kabul etmez. Açık override ifadeleri, kapsam ve yürürlük bilgisiyle öncelik çıkarır. Çözülemeyen maddi çelişkiyi trace’e yazar; uydurma banka politikasıyla kapatmaz.

`AgentSpec` içinde kaynak referansları, koşullar, eylemler, öncelikler, kimlik politikası, ürün politikaları, tarih kuralları, sonuç eşleştirmeleri ve durum/geçiş taslağı bulunur. Kaynak referansı belge SHA-256’sı ve satır aralığı içerir. Yapılandırılmış alanlar yanında kaynaklı genel kurallar ve istisnalar da taşınır; şema yalnızca Public A’ya göre daraltılmaz.

OpenAPI’den gerçek alanlar, required listeleri, enum değerleri ve yanıt sözleşmeleri çıkarılır. Araç adı değişmese de alanların aynı kalacağı varsayılmaz. JSON sözdizimi dışındaki sözleşme kontrolleri desteklenen OpenAPI yapısı üzerinden yapılır; desteklenmeyen referanslar sessizce atlanmaz.

### Workflow üretici

Freya’nın bilinen JSON yapılarını yeniden kullanılabilir şablonlarla üretir. Modele konuşma metinleri, extraction tanımları, geçiş tasarımı ve kaynaklı politika yorumları için başvurulur. Tarih/tutar/sayaç gibi kesin işlemler için doğrulanmış yardımcılar ve brief’ten türetilen parametreler kullanılır. Gereken yeni kod parçaları statik kontrollerden ve örnek davranış testlerinden geçer; yalnızca metin olarak güvenilir sayılmaz.

Başlangıç akışı: açılış/muhatap → kimlik → hesap → ürün görüşmesi ve istisnalar → toplu teyit → kayıt → sonuçlandırma. Node sayısı brief’in ihtiyaçlarına göre değişebilir. Doğrulamadan önce hesap aracı erişimi gibi kısıtlar prompt’a ek olarak node araç listeleri ve geçişlerde uygulanır.

### Görüşme durumu

Bilgi dört aşamada ayrılır: müşterinin söylediği, doğrulanmış, müşteri tarafından onaylanmış ve API’de kaydedilmiş. Tarih veya tutar düzeltmesi eski onayı geçersizleştirir. Parça parça verilen kimlik bilgisi tamamlanmadan doğrulama aracı çağrılmaz.

Ürünler gerçek `get_account` sırası ve kimlikleriyle tutulur. Her ürünün son tarihi, taban tutarı, deneme sayısı, önerisi, onayı, kayıt durumu ve not gerekçesi ayrıdır. Genel konuşma durumu ile ürün durumu karıştırılmaz.

Brief B’de transfer halinde hiç not olmaması gerektiğinden notlar uygun sonuçlandırma aşamasına kadar bekletilir. Kaydedilen ödeme sözleri korunur; yalnızca konuşulmuş teklifler kaydedilmiş sayılmaz. Tam olarak bir kapanış çağrısı hedeflenir ve son banka aracı çağrısı olması kontrol edilir.

### Doğrulayıcı

JSON yapısı, başlangıç node’u, hedef node referansları, erişilemeyen node’lar, araç sözleşmeleri, tanımlanmamış değişkenler, code snippet sözdizimi, routing flag biçimleri ve izinli banka hedefleri kontrol edilir. Kaynak URL izinleri doğrulanmış verilen OpenAPI ve kit yapılandırmasından türetilir.

Statik kontroller bütün konuşma davranışının kanıtı değildir. Örneğin son kapanışın gerçekten bir kez çağrıldığını test kayıtları da doğrular. Freya `dryRun` kontrolü platform sözleşmesini tamamlar; canlı davranış testinin yerine geçmez.

### Test ve teşhis

Geliştirme: kit’in public A/B testleri; seçili vaka düzeltmesi; ardından ortak regresyon kümesi; sonunda üç tekrar ve seçili konuşma stilleri.

Final: yalnızca final girdilerine uygun olduğu doğrulanmış testler çalıştırılır. Sunucu final brief’leri için test ortamı sunmazsa yerel yapısal ve politika kontrolleri yapılır; bu durum `not_evaluated` olarak görünür. Yapay bir public skor üretilmez.

`--style` seçenekleri konuşma biçimini değiştirir, bankadaki gerçekleri değiştirmez. Brief mutasyon testleri ayrı yerel testlerdir: yeni son tarih, farklı kimlik alanı, enum adı veya override notu üzerinden builder’ın genellemesi sınanır.

Hatalar extraction, routing, politika yorumu, hesaplama, araç sözleşmesi, kayıt, kapanış ve platform gecikmesi olarak sınıflanır. Konuşma/tool çıktıları veri kabul edilir; builder’a kaynak kodunu veya değerlendirme sistemini değiştirme yetkisi vermez.

### Düzeltme ve sürüm seçimi

Düzeltici kaynak kuralı, başarısız kontrol, konuşma kesiti ve araç kanıtını alır; adayın ilgili bölümüne değişiklik önerir. Testler, beklenen çıktılar ve resmî scorer değiştirilemez.

Karşılaştırma aynı vaka kümesi, tekrar sayısı ve stil üzerinde yapılır. Önce vakaların bütün tekrarları geçme sayısı; eşitlikte aynı geçerli testlerde kayıtlı başarılı ödeme tutarı, ölçülebiliyorsa, değerlendirilir. Yetersiz karşılaştırılabilir kanıtta incumbent korunur. Küçük testte başarılı challenger, tam ölçülmüş incumbent’ın yerini otomatik alamaz.

İyi aday ve yeni aday ayrı iki slotta tutulur. Yeni aday başarısızsa iyi slot değiştirilmez; eski workflow’u geri yükleme zorunluluğu yoktur. Export öncesi platformdaki normalize edilmiş workflow içeriğinin seçilen adayla tutarlı olduğu kontrol edilir; platformun eklediği metadata farkları ayrı tutulur.

## Süre ve maliyet yönetimi

- Üst sınır: brief başına 1.800 saniye; süreç başlangıcından export ve trace kapanışına kadar.
- İç durdurma hedefi: 1.680 saniye; son 120 saniye restore/publish/export için ayrılır. Gerçek platform gecikmesi gözlenince daha erken finalize edilebilir.
- Bir sonraki çağrı veya test yalnızca tahmini üst süresi ve finalize rezervi kalan bütçeye sığıyorsa başlar.
- Kit’in bir komuta 20 dakika bekleme izni, toplam 30 dakika sınırını uygulamaz. Ayrı deadline şarttır.
- İlk sürüm en fazla bir test temelli düzeltme turu dener; bu hedef değil üst sınırdır. Süre azsa daha erken teslim eder.
- Test süreci takip edilir; arka planda bırakılıp bitmiş sayılmaz. Bir istemci sürecini durdurmak sunucudaki simülasyonu durdurmuş sayılmaz. İptal endpoint’i doğrulanmadan yeni simülasyon başlatılmaz.
- Uzun testte düzenli ilerleme ve kalan süre kaydı tutulur. Model oturum süresi ve platform zaman aşımı ayrı raporlanır.
- Builder’ın model adı açık yapılandırılır, trace’e yazılır; örnek kodun varsayılan modelinin hesaba açık olduğu varsayılmaz. Claude Code oturumunun SDK uyumu ve kullanım koşulları erişim denemesinde doğrulanır; aboneliğin tüm çağrıları kapsadığı varsayılmaz.

## Dosyalar ve trace

Her çalışma; input hash’leri, kit sürümü, kaynak commit, SDK/model kimliği, başlangıç/bitiş, model çağrısı amacı, aday hash’i, workflow/agent/version kimlikleri, test parametreleri, sonuçlar ve seçme gerekçesini kaydeder.

API anahtarları ve takım sırrı loglara yazılmaz. Trace gereksinimi modelin özel akıl yürütmesini kaydetmek değildir; çağrı amacı, işlemler, sonuçlar ve karar gerekçeleri yeterlidir.

Teslim: brief başına Freya export JSON’u ve trace; ayrıca kod commit’i, bağımlılık sürümleri ve yeniden çalıştırma komutu. E-posta nihai teslim adımlarının ayrıca geleceğini söylüyor; form alanları gelince teyit edilir.

## Kapsam dışı

Ses/STT/TTS, gerçek telefon araması, gerçek müşteri verisi, dashboard, RAG/vector veritabanı, fine-tuning, çok sağlayıcılı framework, gizli benchmark keşfi ve el ile final workflow düzeltmesi.

## Uygulama sırası ve karar kapıları

1. Ortam ve mevcut ajanla bağlantı smoke testi.
2. v3 örnek builder’ın ölçümü: önce A, sonra A+B, sonra uygun tekrar/stiller.
3. Deadline, trace, sürüm ve export yöneten minimum koordinatör.
4. Kanıtlı hatalar için AgentSpec, doğrulama ve deterministik politika kontrolleri.
5. Hedefli otomatik düzeltme ve karşılaştırılabilir aday seçimi.
6. Genelleme, tekrar üretim ve teslim provası.

Her aşama çalışır çıktı bırakır. İlk örnek zaten güçlü sonuç verirse gereksiz yeniden yazım yapılmaz; en çok hata azaltan bileşenler öne alınır.

## Takvim ve açık koşullar

11 Ekim 2026 Pazar 20.00 İstanbul: gizli brief’ler. Aynı gün 23.00: teslim kapanışı. Gizli brief’ler açılmadan önce bir commit sabitlenir; sonraki değişiklikler yalnızca izin verilen genel hata düzeltmeleri olarak kaydedilir.

Claude Code oturumu mevcut olduğu kullanıcı tarafından belirtildi; SDK erişimi henüz sınanmadı. Freya API anahtarının yapılandırıldığı doğrulanmadı. Takım anahtarı bir kez oluşturulup korunmalı. Final test/sunum sözleşmesi ve model kullanılabilirliği ilk entegrasyon ve organizatörün son duyurusuyla netleşecek; bunların varmış gibi kabul edildiği kod yazılmayacak.

## Kaynaklar

- [Hackathon](https://www.freyavoice.ai/hackathon)
- [Starter kit v3](https://www.freyavoice.ai/hackathon/build-the-builder-v3.zip): README, örnek builder, freya.py, tools/run_cases.py, tools/score.py, docs ve brief’ler yerelde incelendi.
- Kullanıcının paylaştığı organizatör e-postası ve sunum görüntüleri. Sunumdaki örnekler starter kit’in gerçek sözleşmelerinin yerine kullanılmadı.

## Revizyon 2 — Yürütme kararları

- Önce tek giriş noktasından çalışan küçük builder. SDK çağrısı araçsızdır; Python brief, verilen OpenAPI, platform belgeleri ve referans JSON’u modele veri olarak verir, dönen JSON’u doğrular ve yazar. Ayrı bir motor seçimi yok.
- AgentSpec tam derleyici değildir: ham brief korunur; kaynaklı kural listesi ve kapsama haritası üretilen workflow ile birlikte saklanır. Kapsama beyanı davranış testi sayılmaz.
- Önce erişim ve baseline; gelişmiş kayıt motoru veya tarih parser’ı yalnızca deney gerektirirse eklenir.
- Son çalışma export’u checkpoint edilir. İki slot incumbent/challenger olarak kullanılır; test edilen sürüm export ile bağlanır.
- Test manifest’i veya açık public suite seçimi yoksa ledger testi yapılmaz. Endpoint keşfi yoktur.
- Kit snapshot’ı değiştirilmez. Resmî test aracı yazılabilir run kopyasından çağrılır.
- Yazma araçlarında otomatik retry kapalıdır. Açık başarısızlıkta brief’in sayısı kadar uygulama retry’ı; sonucu bilinmeyen timeout için garanti iddia edilmez, politika yorumu trace’te görünür.
- Kapsam dondurma kapısı: minimum builder A/B export ve trace üretmiyorsa genişletmeler durur. Önce mevcut akış düzeltilir. Gece yarısı gizli ajan teslimi yapılmaz.
- Erişim/baseline: bu çalışma; tarih ve kayıt deneyleri: baseline sonrası; final prova: gizli brief açılmadan önce. Sahip: bu sohbetin uygulayıcı ajanı; anahtar erişimini kullanıcı sağlar.
- İlerleme her aşamada outputs/ILERLEME.md ve Git commit’leriyle korunur.

## Revizyon 3 — Spec derleyicisi (10 Ekim, ölçüme dayalı)

- Neden: modelin tam workflow JSON'u yazması 720 sn'lik üretim sınırını aştı (ilk canlı run). Workflow'un tamamı, 30 dakikalık bütçede güvenilir biçimde tek çağrıyla üretilemiyor.
- Model (araçsız, tek çağrı, ~45-90 sn) yalnızca BankSpec döndürür: kaynaklı kural kaydı, kapsama, çağrı değişkenleri ve saat değişkeni, açılış cümlesi, kimlik soruları (OpenAPI enum'undan), takvim, ürün alanları, bantlar ve deadline türleri, gerekçesiz sonuçlar, araç açıklamaları ve faz bazlı operasyonel checklist'ler.
- `validate_spec` her alanı verilen OpenAPI'ye karşı denetler. İhlal olursa bir düzeltme çağrısı yapılır, sonra hata verilir.
- `compile.py` yalnızca platform mekaniği içerir; banka kuralı içermez. Brief'ler system_prompt'a birebir girer. Tarih ve ürün olguları sandbox kod node'unda hesaplanır (yalnızca json, re ve datetime). Kimlik bayrağı account erişimini routing ile açar. Kancalar her araç sonucuna what_to_do_next ekler.
- Negotiate node'unda model akıl yürütmesi açık. Ölçüm: tarih ve deneme sayısı hataları düzeldi; tur medyanı 3 sn'den 6 sn'ye çıktı.
- Genelleme provası: tests/fixtures/genx (ham materyal, memo override, yeniden adlandırılmış alanlar ve enum'lar) temiz spec üretti ve dryRun'dan geçti.
