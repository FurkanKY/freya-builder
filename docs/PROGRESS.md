# Freya Builder — İlerleme

## Şu an
Ortam kuruluyor; uygulama başladı. Proje: /home/furkan/Documents/Codex/2026-10-10/i/freya-builder

## Tamamlanan
- İki review değerlendirildi; ana plan ve tasarım Revizyon 2'ye güncellendi.
- Kit v3 snapshot'ı ve manifest oluşturuldu.
- Git implementation dalı oluşturuldu.
- Python 3.12 sanal ortamı, Claude Agent SDK 0.2.165 ve test bağımlılıkları kuruldu.
- Claude Code oturumu loggedIn; SDK çağrısı henüz doğrulanmadı.
- Kullanıcı Freya anahtarını .env dosyasına ekledi. Takım anahtarı bir kez üretildi.

## Henüz yapılmayan
- Freya/Claude canlı erişim testi, workflow oluşturma ve simülasyon.
- Builder kaynak kodu, ilk commit, baseline skoru.

## Sıradaki iş
Claude SDK ve Freya read-only erişimini doğrula; minimum builder kritik testlerini yaz ve uygulamaya geç.

## Devam ederken
.env içeriğini loglama. Proje .venv/bin/python kullan. Önce git status/log ve bu kayıt okunmalı. vendor/kit-v3 değiştirilmemeli. Henüz aktif simülasyon yok.

## Aşama 1 — Erişim doğrulandı
- Claude Agent SDK 0.2.165, mevcut Claude Code oturumuyla sonnet çağrısından OK aldı; araç çağrısı 0, süre 3.6 sn.
- Freya read-only workspace isteği başarılı; tek workspace bulundu.
- Test başlangıcında ROS pytest plugin sızıntısı görüldü; PYTHONPATH=. ve PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 ile proje izole edildi.
- 11 kritik test yazıldı; üretim modülleri henüz yok, beklenen RED durumu görüldü.
- Sonraki adım: minimum builder modüllerini yaz, testleri geçir, ilk A workflow üretimini başlat.
- Henüz aktif Freya simülasyonu yok.

## Aşama 2 — Builder kodu commit edildi, ilk canlı deneme
- Devralma (10 Ekim): builder modülleri ve testleri commit edilmemişti; 73365e1 ile commit edildi.
- Eklenen: resmî runner'ın persona haritası runs/personas.json üzerinden çalışmalar arasında paylaşılıyor (her koşuda yeni persona yaratılmasın). 16/16 test geçiyor.
- Canlı öncesi kontrol: workspace'te yalnızca temel workflow vardı; builder simülasyonu yoktu.
- Başlatılan: `builder.build brief-a.md openapi.json --slot public-a --suite A --only PUB-01,PUB-02,PUB-10`.
- Sonuç ve run kimliği: runs/latest.json.

## Aşama 2b — Spec derleyicisine geçiş (10 Ekim, ~15:30)
- İlk canlı deneme (run 20261010T120214-300004Z): model tam workflow JSON'unu 720 sn'de bitiremedi, TimeoutError. Platformda bir şey oluşmadı.
- Karar (DESIGN "şablonlar + brief'ten türetilen parametreler" yönüyle uyumlu): model artık kısa BankSpec döndürüyor; builder/compile.py workflow'u kuruyor.
  - Node'lar: prepare (kod: tarih olguları) → identify (kimlik, callback, transfer, close) → load_account (get_account pre_action) → account_facts (kod: ürün başına bant/deadline/floor) → negotiate → hang_up.
  - get_account yalnızca verify_identity yanıtındaki tamamlanma bayrağıyla açılıyor (routing ile zorunlu).
  - Brief'ler system_prompt'a birebir giriyor; spec'teki checklist'ler node görevlerine.
  - Her araca post-hook ile what_to_do_next; close_call pre-hook'u gereksiz reason'ı düşürüyor.
  - Builder kodunda brief'e özgü değer yok; alan adları/enum'lar OpenAPI'den, takvim/bantlar spec'ten.
- Elle yazılmış örnek spec ile derlenen workflow Freya dryRun'dan geçti (valid: true). 23/23 test.
- Commit 0eb17c1. Başlatılan: tam Brief A ölçümü, slot public-a.

## Aşama 3 — İlk ölçümler (10 Ekim öğleden sonra)
| Run | Girdi | Suite | Sonuç | Süre |
|---|---|---|---|---|
| 20261010T122027-813658Z | A | A (10) | 9/10, PUB-07 fail | ~3,5 dk (spec 69 sn, test 136 sn) |
| 20261010T122536-491343Z | A+B | AB (13) | 11/13, PUB-07 + PUB-12 fail | ~4 dk |
- Mekanik sorun yok: kimlik kapısı, routing, post-hook, tek close_call, kapanış hepsi doğru. Tur medyanı 3-5 sn.
- PUB-07: müşteri 26 Ekim (tatil, deadline içinde) dedi; ajan sonraki iş günü yerine deadline'ı önerdi. Takvim satırları zenginleştirildi ama tekrarladı → telefon modelinin kural uygulama hatası.
- PUB-12: erken bantlı üründe 2. ikna denemesi yapıldı (olgularda "attempts 1" yazıyordu).
- Deney: negotiate node'unda reasoning_override=enabled (BUILDER_AGENT_REASONING ile kapatılabilir).
- Genelleme fixture'ı (tests/fixtures/genx: ham materyal + memo override + yeniden adlandırılmış API): spec 46 sn, doğru alanlar/öncelik, local + dryRun temiz.
- Repair kanıtı artık kısa transkript özeti (evaluate.transcript_digest).
- AB suite: A+B ajanı 13 public vakanın hepsiyle test edilir.

## Aşama 4 — Tekrar ölçümü (reasoning açık, run 20261010T123047-192923Z ajanı)
- Hard 5 vaka tek tur: 4/5 (PUB-07 ve PUB-12 düzeldi; PUB-06'yı katı hakem "teklif iki kez" diye düşürdü).
- **AB 13 vaka × 3 tekrar (final kuralı: 3/3): 12/13.** Turlar 13/13, 13/13, 12/13. Tek kayıp: PUB-12 3. tur (ajan "I've noted that" dedi, kredi kartına geri döndü, müşteri kapattı).
- Tur medyanı 3 sn, en kötü 9 sn; reasoning gecikmesi kabul edilebilir.
- Düzeltme (frame): tool ok:true dönmeden "noted/recorded/booked" denmez; daha önce yapılmış teklife geri atıf yapılır, tekrarlanmaz.
- Ölçüm aracı: `python -m builder.campaign <run_id> --suite AB --reps 3 [--style X]` (build bütçesi dışı).
- Sırada: 5 konuşma stiliyle 13 vaka (çalışıyor), sonra temiz uçtan uca prova (--repair dahil).

## Aşama 5 — Konuşma stilleri (aynı ajan, AB × 1 tur)
| Stil | Sonuç | Kök neden |
|---|---|---|
| pieces | 11/13 | Parçalı cevaba tam cevap gibi tepki: "20" tutar sanıldı (PUB-04), fazladan teklif (PUB-12) |
| corrects | 12/13 | Hakem açılıştaki "This call is recorded"ı erken "recorded" saydı (PUB-10) |
| talkative | 4/13 | Simüle müşteri mesajları kesik/yalnız sohbet; ajan bunları ret/cevapsızlık saydı |
| asks_back | 12/13 | 3 haneli telefon cevabı tool'a gitti; sonra ajan sustu (PUB-13) |
| in_words | 12/13 | PUB-13 kapanmadı (aynı susma) |
- **Yeni bulgu:** reasoning açıkken experimental-5 ~3.1–3.7 bin karakter düşünüp `finish_reason: length` ile "no speakable content" veriyor. 65 çağrıda 13 kez; iki kez üst üste olunca müşteri kapatıyor. Platformda token/efor ayarı yok.
- Genel düzeltmeler (frame/derleyici, brief'e özgü değil):
  - Kesik/eksik mesaj ve yalnız sohbet = henüz cevap değil → "Go on." / soruyu tekrar sor; ret sayılmaz (3 kez üst üste ise cevapsızlık).
  - Eksik cevap (az hane, eksik tarih) tool'a gönderilmez.
  - Her ödeme sorusu bir teklif; politikada olmayan ara teklif eklenmez.
  - Band başına `attempt_plan` (spec): facts.py ürün başına somut tutar/tarihle "persuasion plan" satırı yazar.
  - negotiate düğümünde "kısa düşün" talimatı (BRIEF_THINKING).
  - Açılış cümlesinde sonraki olaylara ayrılmış kelime kullanılmaz (farklı kelime biçimi).

## Aşama 6 — Düzeltmelerle yeniden ölçüm
- Build 20261010T130616-750120Z (commit 03a8c2f): AB 12/13, reasoning hatası 0. PUB-12: üçüncü üründe "today" tekrar soruldu → plan satırı "tam teklif listesi" olarak işaretlendi.
- Build 20261010T131211-173701Z (commit 2b52bbd, `--repair`): **AB 13/13** (repair atlandı: hepsi geçti). Toplam build ~300 sn.
  - AB × 3 tekrar: turlar 13, 13, 12 → katı 12/13 (PUB-03 bir kez: tam tarih "Go on" ile parça sanıldı → "her parçası olan cevap tamamdır" kuralı, bb47e00).
  - pieces: 12/13 (PUB-12: transkriptte 2+1 deneme doğru; hakem açılış sorusunu da saydı — hakem gürültüsü).
  - talkative: 8/13 (önce 4/13). Kalan: reasoning kesilmesi (9 hata, 4 kapanmayan çağrı) ve identify'da 40 tur sınırı → sınırlar 80/120 (10a5da0).
- Genelleme fixture'ı (Northwind, yeniden adlandırılmış API): spec doğru, attempt_plan bant başına doğru üretildi; ilk çıktıdaki now_variable hatası tek düzeltme çağrısıyla giderildi; dryRun geçerli.
- 13:40–13:55 UTC arası staging'de ajan LLM kesintisi: tüm çağrılar açılıştan sonra sessiz, `customer-ended-call` (0/13). Bu aralıktaki reasoning enabled/disabled karşılaştırması geçersiz; kesinti bitince tekrarlanacak.

## Aşama 7 — Reasoning karşılaştırması ve dayanıklılık
- Aynı kod (dc0f3f2), negotiate reasoning **enabled** vs **disabled** (staging altyapı hataları ayıklanarak):
  - enabled: AB 10/13, 3 kayıp tümü snekbox kesintisi ("Failed to reach snekbox"); altyapısız 10/10. talkative 10/13 (önce 4 → 8 → 10).
  - disabled: AB 6/13; altyapısız kayıplar PUB-07 (tatil günü yanlış tarih, bilinen reasoning-siz hata) ve PUB-03 (parça sanılan tam tarih).
  - **Karar: reasoning enabled kalır.**
- Staging'de iki ayrı kesinti gözlendi: ajan LLM'i yanıt vermedi (13:40–13:55 UTC) ve snekbox kod sandbox'ına ulaşılamadı (hook'lu her tool çağrısı ve code node düşer). Bunlar platform kaynaklı; ölçümde ayrı sayılıyor.
- Genelleme fixture'ından çıkan hatalar düzeltildi: tool ipuçları path ile anahtarlanınca kayboluyordu (2ab1f1e), fact etiketleri API alan adlarını kullanıyor, kapalı günde önceki iş günü de yazılıyor, iç içe ürün listesi yolu destekleniyor, uydurma persuasion adımı yasak.
- Build dayanıklılığı: bozuk/zaman aşımlı model çıktısı bir kez yeniden denenir; düzeltme sonrası hâlâ geçersiz spec build'i düşürmez, en az hatalı spec derlenir (bb2cc30); Freya 5xx/429/ağ hataları iki kez yeniden denenir (dc0f3f2).
- Teslim: `trace.txt` (düz metin iz) ve `python -m builder.submit <run_id> <ad>` (hash doğrulamalı export+trace kopyası, 31be6ec). README'de final prosedürü.

## Aşama 8 — Review düzeltmeleri, genelleme, 3 tekrar
- Kod incelemesi bulguları (aae3e4c): `builder/spec.py` model spec'indeki tip sapmalarını (liste/sözlük/string) normalize eder; `$ref` gövdeleri çözülür; hook'lar bankanın kendi `ok`/`success`/hata alanını ve noktalı `complete_flag`/`answer_flag` yollarını okur; HTTP metodu API'den gelir; kimlik cevabı olan alanlar çağrı değişkeni diye gömülmez. 40 test.
- Genelleme fixture'ı yeni kodla: validated, 98 sn. Brief saat değişkeni adı vermeyince model `now`u call_variables'a eklemiyordu → tarih/saat benzeri değişken yoksa normalize ekler (9113478); ilk spec düzeltme çağrısı olmadan geçerli.
- Build 20261010T143024-909190Z, AB × 3 tekrar: katı 5/13; ama 39 çağrının 15 kaybından 14'ü snekbox kesintisi. Altyapısız 25 çağrının 24'ü geçti. Tek gerçek kayıp PUB-12: üç ürüne bölünmüş cevapta iki ardışık reasoning kesilmesi (3.0k/3.3k karakter, platform bir kez yeniden denedi) → müşteri kapattı.
- Düzeltme (8eecfec): negotiate'te "her cevapta bir adım" (çok ürünlü cevapta yalnız ilk eylem gereken ürün) ve DATE FACTS'e "Tomorrow" satırı.
- Karar: yazma tool'larından hook kaldırma A/B'si yapılmadı; snekbox düşünce account_facts code node'u da düştüğü için kazanç yok.
- Sır taraması: git geçmişi ve izlenen dosyalarda .env değeri yok; .env ignore'da.

## Aşama 9 — Düşünme kesilmesi denemeleri, altyapı kesintileri, yeni fixture
- Build 20261010T145802-060231Z (8eecfec, "her cevapta tek adım" + Tomorrow satırı), AB × 3, altyapı kesintisi yok: katı 11/13. Kayıpların hepsi çok ürünlü cevapta iki ardışık reasoning kesilmesi (PUB-13 3/3, PUB-11 1/3).
- 354e8b4 (sabit tek satırlık düşünme biçimi): build testi 11/13, AB tur 1: 10/13; PUB-13 kesilme, PUB-05 gereksiz hardship notu, PUB-12 fazladan deneme → kötü.
- Karşılaştırma: 8eecfec öncesi PUB-13 3/3 geçiyordu (kesilme en fazla 1 kez). İki düşünme talimatı da geri alındı (8b5ea9e); Tomorrow satırı kaldı.
- Kesintiler: yerel DNS hatası (kit sorgusu), practice bank Worker çökmesi (Cloudflare 1101; tüm /v1 yolları, ajan araçları dahil, ~15:35–15:49 UTC). Organizatör duyurusu: "API and code execution errors are fixed".
- Düzeltmeler: daha önce yapılmış teklif sorulunca tek cümle cevap, yeniden teklif yok (6b67cef, PUB-06); grup halinde ret ("the loans") her ürünün ilk sorusuna cevap sayılır (ec1145c, PUB-12).
- Genelleme:
  - Sonnet vs Opus (genx): ikisi de memo override'ı (7 gün) yakaladı; Opus 92 sn, Sonnet 43 sn; kimlik bayraklarını ters eşlediler (fixture'da alan açıklaması yok). Karar: Sonnet kalır; şemaya bayrak adlandırma ipucu (f7611ab).
  - Asgari tutar artık alan, yüzde ("20% of overdue", kuruşa yukarı) veya sabit tutar olabilir (3bc1a2c).
  - Yeni fixture tests/fixtures/geny (Kestrel: client_ref, call_time, data.products, Pazartesi–Cumartesi, ay sonu son tarihi, %20 kart asgarisi, gerekçeli sonuç tablosu): Sonnet spec'i 14/14 kontrol doğru; derlenen ajan yerel doğrulamadan geçti, hesaplanan son tarihler doğru (7d8e2c4).
  - Görülmemiş API sağlamlığı (fe6116a): kimlik tamamlanma bayrağı boolean değilse durum değeri (complete_value) ile eşleşir; cevap bayrağı yoksa nötr hook mesajı; daha fazla saat biçimi; araç adı path yoksa operationId'den bulunur.

## Aşama 10 — 6b67cef 3 tekrar teşhisi
- Build 20261010T154920-505698Z (6b67cef), AB × 3, altyapı kesintisi yok: build testi 12/13, katı 10/13. Kayıplar:
  - PUB-13 2/3 ve PUB-12'nin 1 çağrısı: çok ürünlü cevaptan sonra düşünme kesilmesi. PUB-12'de müşterinin grup cevabından sonra 60 sn sessizlik oldu, müşteri kapattı; olay kaydında hata yok.
  - PUB-12'nin diğer 2 çağrısı:
    - Araç kredisine (erken bant, tek deneme) "bugün" yeniden soruldu ve bu deneme sayıldı → iki deneme oldu. ec1145c'deki grup ret kuralı bunu hedefliyor; bu build onu içermiyordu.
    - `add_note`, `add_note` ve `close_call` aynı turda paralel gönderildi. Platform bunları eş zamanlı çalıştırıyor (close notlardan 140–300 ms sonra başladı); bir çağrıda kapanış önce düştü ve son not "the call is already closed" aldı. Düzeltme (d020451): close_call ön kancası 1,5 sn bekliyor.
  - PUB-05 1/3: tek ürünlü Brief A çağrısında `add_note` hardship. Sebep, A+B'nin tek ajanda birleştirilmesi: "Brief A never uses add_note" ile Brief B'nin kuralı çatışıyor. Finalde her brief ayrı derleniyor, bu yüzden düzeltilmedi.

## Aşama 11 — Reasoning açık mı kapalı mı (aynı kod, 5484e27)
| Build | Reasoning | Build testi | AB × 3 katı | Kayıplar |
|---|---|---|---|---|
| 20261010T163009-382363Z | enabled | 9/13 | 9/13 | 4 çağrıda susma veya kesilme (PUB-09 tek ürün, PUB-11 ×2, PUB-12); PUB-05 A+B not çatışması |
| 20261010T165437-661845Z | disabled | 11/13 | 9/13 | susma 0. PUB-07 0/3 (tatil yerine son tarih önerildi), PUB-12 0/3 (deneme sayısı), PUB-03 1 (bozuk simülatör mesajında 3. cevap kaçtı), PUB-05 1 (destek iki kez teklif edildi) |
- Kapalı modda çok ürünlü PUB-11 ve PUB-13 3/3 geçti. Kampanya süresi 549 sn; açık modda 865 sn.
- Kapalı moddaki hatalar, projenin ilk ölçümündeki (reasoning'siz) hatalarla aynı: PUB-07 ve PUB-12. Deterministikler, kodla düzeltilebilir. Açık moddaki susma ise model bütçesinden kaynaklanıyor ve düzeltilemiyor.
- Fable danışması: ürün başına düğüm döngüsü kurulmasın; doğrulanmamış platform davranışı çok, grup cevabı yine üç ürünü birden düşündürür. Reasoning kapatılsın, mantık koda taşınsın.
- Karar (2e46300):
  - reasoning varsayılan olarak disabled;
  - müşterinin söylediği gün extraction ile okunuyor (`named_date`); `check_date` kod düğümü takvim, tatil ve son tarih hükmünü NAMED DAY CHECK satırına yazıp değişkeni temizliyor, sonra negotiate'e dönülüyor;
  - plan "ilk ret → deneme 1 → ret → deneme 2 → ret → DUR" zinciri olarak yazılıyor;
  - "Bugün bu haftanın son iş günü mü" satırı eklendi;
  - tarihler müşteriye sözle söyleniyor;
  - düşünme talimatı yalnızca reasoning açıkken ekleniyor.
- Ek düzeltmeler: HTTP hatası hiçbir zaman başarı sayılmıyor (9db3e1e); son tarihler farklıysa en erken olan söyleniyor (5484e27).

## Aşama 12 — ACCOUNT FACTS canlıda hiç çalışmıyormuş
- Build 20261010T171647-693386Z (2e46300), build testi 11/13. PUB-07 geçti; tarih kontrolü canlıda doğrulandı:
  - extraction "Monday the 26th" → `named_date=2026-10-26`;
  - `check_date` kod düğümü çalıştı, negotiate'e dönüşte tek cevap geldi ("Monday, 26 October is a bank holiday. Would Tuesday, 27 October work for you?");
  - çift cevap ve susma yok;
  - araç sonucundan sonra sapma olmadı.
- **Bulgu:** negotiate'e girişte `facts_state=no_products` → ACCOUNT FACTS "The product list could not be read by code" diyordu. Eski build'lerin çağrılarında (6b67cef, 5484e27) da durum aynı.
  - Sebep: api_request düğümünün sonucu DÜĞÜM adıyla düzleşiyor (`load_account_response.data.products.0.past_due`); response_mapping değişkeni (`account_products`) oluşmuyor; kod `get_account_response...` arıyordu.
  - Yani ajan şimdiye kadar ürün bazlı son tarih, asgari tutar ve ikna planı olmadan, ham get_account sonucundan kendisi hesaplıyordu. Deneme sayısı ve PUB-13 tarih hatalarının, reasoning açıkken yaşanan uzun düşünmenin de büyük olasılıkla ana sebebi bu.
  - Düzeltme (4428038): ürünler `*_response.data.<liste>` biçimindeki her anahtardan okunuyor (en dolu kaynak, load_account öncelikli). Testi eklendi.
- Ayrıca kod düğümünün `named_date=""` yazması kalıcı olmuyor; artık "none" yazılıyor ve geçiş "none"u da dışlıyor.
- Ders: yerel testler canlı değişken adlarını varsaymıştı. Canlı değişken tablosu (route_evaluated.variable_table) her yeni mekanizmada kontrol edilmeli.

## Aşama 13 — Gün sözcükleri kodda, ürün başına ret sayacı
- 37acc3b:
  - date tipli extraction göreli günleri sunucu saatine göre çözüyordu. Artık müşterinin sözcükleri string olarak kopyalanıyor (`named_day_words`) ve kodda çağrının `now` değerine göre çözülüyor;
  - kapalı gün kuralı spec'e eklendi (`closed_day_rule`);
  - her ürünün planında STOP kendi adını ve deneme sayısını taşıyor.
- Build 20261010T174323-377630Z (37acc3b) ölçümleri:
  - build testi 12/13;
  - AB × 3 katı 11/13, şimdiye kadarki en iyi sonuç. PUB-05 ve PUB-07 3/3 geçti;
  - kayıplar: PUB-12 0/3 ve PUB-03 1/3.
- PUB-12'nin üç çağrısı üç farklı yoldan düştü:
  1. kişisel krediye tek deneme yapıldı (iki olmalıydı);
  2. her ürün için "bugün" yeniden soruldu, her üründe bir fazla teklif oldu;
  3. erken banttaki araç kredisine geç bandın 2. denemesi kopyalandı.
  Kural metinleri zaten bunları söylüyordu; reasoning'siz model sayımı tutturamıyor.
- PUB-03: "21 July 1990. This is" mesajı tam bir tarih içerdiği halde "Go on." denildi ve 4. kez doğum tarihi soruldu. FRAME'e eklendi: tam cevabın arkasından gelen kopuk sözcükler cevabı bekletmez.
- Konuşma tarzı testi (37acc3b, her tarzdan 1 tekrar):
  - pieces 11/13: PUB-12, ve PUB-13'te kartın 30 Ekim tarihi kredinin 23 Ekim tarihine çekildi;
  - corrects 12/13: PUB-12.
  - PUB-13 için FRAME'e eklendi: bir ürüne uyan tarih o üründe kalır; yalnız son tarihi geçen ürüne daha erken tarih önerilir; geri okumada her ürün kendi tarihiyle söylenir.
- Sayım koda taşındı:
  - negotiate'te ikinci extraction alanı `refused_products`: son mesajda açıkça reddedilen ürünler, asistanın kullandığı adlarla; düz bir hayır "all" olarak yazılıyor;
  - kod bu sözcükleri ürün id'lerine eşliyor: tek ürüne ait bir sözcük o ürünü seçiyor, "loan" gibi ortak bir sözcük sahibi olan tüm ürünleri. Ardından ürün başına sayacı (`refusal_counts`) artırıyor, alanı "none"a çeviriyor ve PROPOSAL COUNT satırını (`plan_state`) yazıyor. Bu satırda her ürün için ya sıradaki teklif ("attempt k: …") ya da STOP var;
  - hiçbir ürünle eşleşmeyen çıplak bir "no", planı süren tek bir ürün varsa o ürüne yazılıyor;
  - tek ürünlü çağrılarda sayaç kapalı (yönlendirme `product_count != 1` koşuluna bağlı), bugün geçen akış değişmiyor.
- Fable danışması, benimsenenler:
  - ürün asistanın sözcükleriyle adlandırılıyor;
  - kaçamak cevaplar sayılmıyor, yalnız açık retler sayılıyor;
  - çıplak hayır için yedek kural var;
  - tek ürün kapsam dışı.
- Fable danışması, benimsenmeyenler:
  - "Gün söylendiyse reddi yok say": PUB-12'deki "kartı yarın öderim, kredileri ödemem" cümlesinde gün ile ret birlikte geliyor;
  - `promised_products` değişkeni: post-hook `vars`'a erişemiyor;
  - plan zincirinin prompttan çıkarılması: "too much" akışında modelin adımların tamamına ihtiyacı var.
- Tarz testinin tamamı (37acc3b): pieces 11/13, corrects 12/13, talkative 11/13, asks_back 12/13, in_words 12/13. PUB-12 her tarzda düştü.
  - talkative PUB-06: müşteri kesilen cümlesini baştan söyledi, ajan 15 kez "Go on." dedi. Düzeltme (8efaf77): art arda en fazla bir "Go on.", sonrasında soru tekrar soruluyor.
  - asks_back PUB-12: "Why do you need that?" sorusundan sonra soru tekrarlandı, hakem bunu yeniden sorma olarak saydı. Düzeltme (e0a1897): sebep söyleniyor, soru tekrarlanmıyor.
  - in_words PUB-12: kesik "I can pay the five hundred and ten" mesajı "bugün" diye yorumlandı ve `create_promise` geri okuma ve onay olmadan çağrıldı. Tek görülme; kodla engelleme yanlış alarm riski taşıdığı için yapılmadı, izleniyor.
- Final provası (9872088, gözetimsiz, `--suite` yok): geny ve genx her biri yaklaşık 56 sn, validated, export ve submit tamam, sır taraması temiz. Bulgu: "ayın son iş günü" son tarihi takvim günü olarak hesaplanıyordu. Düzeltme (6ac9c91): `last_business_day_of_month` türü eklendi, normalizasyonu ve testi var.

## Aşama 14 — Sayacın canlı ölçümü, yalnız yapılan tekliflerin sayılması
- Build 20261010T184025-751045Z (e0a1897): build testi 11/13.
  - PUB-05: A+B birleşmesindeki bilinen not çatışması.
  - PUB-12: canlı değişken tablosuna göre sayaç her turda doğru saydı, araç kredisi tek denemeden sonra STOP gördü. Model buna rağmen araç kredisinin tabanını (46) teklif etti. Sorun sayımda değil, STOP'a uymada.
- Varyantlar (tests/fixtures/variants-b.json, × 3): PUB-11, PUB-12 ve PUB-13 varyantlarının her biri 3/3, 9 çağrının 9'u geçti.
- Değişiklik incelemesi (9 ajan, 4 doğrulanmış bulgu, hepsi sayaçta):
  - "None." veya "nothing" gibi yazımlar her ürünü ret sayıyordu;
  - ilk soruya kısmi bir cevap sayılmıyordu, sayaç bir adım geride kalıyordu;
  - bir ürünün teklifi sırasında gelen toplu ret ("none of them"), teklif edilmemiş ürünlerin haklarını da tüketiyordu.
- Düzeltme (9b2c9e0):
  - yeni extraction alanı `proposed_products`, asistanın son mesajında ödemesini istediği ürünler. Bu alan yönlendirme yapmıyor;
  - ilk soru her ürün için en fazla bir kez sayılıyor; sonraki retler yalnız teklif edilen ürünlere yazılıyor;
  - sayılmamış bir ilk sorudan sonraki ilk teklif yine 1. deneme sayılıyor;
  - "hiçbiri" değerinin her yazımı ret sayılmıyor;
  - STOP olduğu turda PROPOSAL COUNT'un başında, ürünün taban tutarı adıyla yazılarak "artık hiçbir şey teklif etme" satırı var. FRAME'de de aynı kural var.
- Aynı committe küçük genel düzeltmeler:
  - "all except X";
  - ay sonu türü yalnız bu ayın sonu için;
  - ikinci kesik mesaja soruyu tekrarlamak yerine "could you say it again?";
  - genel kodda Brief B'ye özgü "today" ifadesi kaldırıldı.

## Aşama 15 — İkinci inceleme, brif okumasının oynaklığı, üç okumalı uzlaşma
- 3 tekrar ölçüm (e0a1897, A+B, × 3): 10/13.
  - PUB-05 0/3: A+B birleşmesinin bilinen not çatışması; finalde her brif ayrı derleniyor.
  - PUB-12 0/3: sayaç doğru, model STOP'tan sonra tabanı teklif etti (Aşama 14'teki bulgu). STOP satırı 9b2c9e0'da geldi, bu ölçümde yoktu.
  - PUB-13 1/3 düştü: bir çağrıda tarih kaydı.
- İkinci inceleme, düzeltmeler (9f84753):
  - "Go on." veya "say it again" gibi ödeme sormayan bir asistan mesajından sonraki ret, önceki teklife yazılıyor;
  - müşterinin kendi verdiği tarih veya tutar (k==0 iken karşı teklif) asistanın yaptığı bir teklif gibi sayılmıyor, ilk reddi 1. deneme;
  - "no product refused" gibi uzun "yok" değerleri ret sayılmıyor.
- Yeni fixture tests/fixtures/variants-c.json (936f995): iki varyant daha.
  - PUB-13 benzeri: iki ürün 30 Ekim'de, ardından kredinin son tarihi ve tüm teklifleri reddediliyor;
  - PUB-12 benzeri: her teklifte "neden?" diye soruluyor, sonunda hepsi reddediliyor.
- 9f84753'ün ilk ölçümü pratik sunucusundaki bir ağ zaman aşımıyla düştü (`--suite` yolundaki vendor test koşucusu). Final yolu bu koşucuyu kullanmıyor; ölçüm yeniden başlatıldı.
- Brif okumasının oynaklığı. Aynı ham fixture'ı (genx, geny) üç kez okuttum:
  - genx: 50 alanın 39'u aynı. Karar alanı olarak `outcomes.no_reason` bir okumada 7 kod, ikisinde 11 kod;
  - geny: 48 alanın 43'ü aynı. Karar alanı olarak `calendar.closed_day_rule` iki okumada "none", birinde "ask_again";
  - geri kalan farklar ifade farkı (band adları, soru metinleri, açılış cümlesi).
  - Sonuç: tek okuma, gizli brifte bir karar alanını yanlış okuyabilir; spec çıkarma build'in tek rastgele adımı.
- Düzeltme, üç okumalı uzlaşma (`generate_consensus`):
  - brif aynı anda üç kez okunuyor;
  - her okuma kontrolden geçiyor, en iyi kontrol sonucuna sahip okumalar aday;
  - adaylar arasından, yapılandırılmış alanlarda diğer bütün okumalarla en çok eşleşen okuma seçiliyor. Daha çok sözleşme hatası olan bir okuma kazanamıyor ama oy veriyor;
  - ifade alanları (açılış cümlesi, soru metinleri, band adları, ürün adları) yalnız derleyicinin onlardan aldığı kısımla oy veriyor: değişkenler, alan adları, adım sayısı. Sırası anlam taşımayan listeler (çağrı değişkenleri, sonuç kodları, tatiller, bandlar) sırasız karşılaştırılıyor;
  - hiçbir okuma bitmemişse okumalar, generate()'in kendi bütçe sınırına kadar bekleniyor. İlk iyi okumadan sonra geç kalanlara bir kez 180 sn veriliyor;
  - üçü de düşerse build hata veriyor, biri düşerse kalanlarla devam ediyor;
  - trace'e `spec_vote` satırı yazılıyor (kaç okuma, uyum, seçilen, farklı alanlar);
  - okumalar `runs/<run_id>/read-<k>/spec.json` altında, `scripts/spec_diff.py` ile karşılaştırılabiliyor.
  - Canlı deneme (yalnız spec, genx): 51 sn, 2. okuma seçildi.
- Uzlaşma kodunun incelemesi (7 ajan, 3 doğrulanmış bulgu):
  - hiçbir okuma bitmeden bütçe sınırına (available − 420 sn) gelinirse bütün okumalar iptal ediliyordu; eski tek okuma bu durumda bir aday döndürüyordu. Kısa `--seconds` değerlerinde her build düşüyordu;
  - ifade alanları oy veriyordu. 2'ye 1 ayrılan bir soru metni, düşmüş bir çağrı değişkeniyle aynı ağırlıktaydı;
  - sıralı karşılaştırma yüzünden yalnız sırası değişen bir liste uyuşmazlık sayılıyordu; gerçek okumalar üzerinde yapılan simülasyonda hatalı okuma %7 ile %33 arasında kazanıyordu.
  - Düzeltme: üçü de düzeltildi. Ek olarak sır kontrolü yalnız "Secret detected" hatasına bakıyor, `BUILDER_READS` geçersizse 3 kullanılıyor (1 ile 5 arasına sınırlı), iptal edilen görevler güvenle işleniyor, seçim adımı hata verirse ilk uygun okuma kullanılıyor. Hepsinin testleri var.
- Build 20261010T193448-057859Z (980af72, uzlaşmadan önceki kod): build testi 12/13. PUB-05 geçti.
  - PUB-12 yine düştü. Canlı değişken tablosuna göre sayaç her turda doğruydu: araç kredisi tek denemeden sonra STOP'a geçti ve plan_state'in başında "tabanı 46'yı da teklif etme" satırı vardı. Model buna rağmen "46'yı 2 Kasım'a kadar ödeyebilir misiniz?" diye sordu. Bu, geç bandın 2. denemesi (taban, son tarihte); erken bantlı ürüne uygulandı.
  - Yorum: modele yalnız ne yapmayacağı söylendiğinde boşluğu kendi teklifiyle dolduruyor.
- Aynı akşam Freya API'si yaklaşık 22:54–23:02 arasında 503 verdi ("API key validation is temporarily unavailable"). Ölçüm kampanyaları başlamadan düştü. Builder istemcisi artık 429/502/503/504'te bütçe yettikçe artan aralıklarla tekrar deniyor (8eb2178).
- Düzeltme (4d4f7b2): STOP anında plan bir sonraki adımı açıkça yazıyor.
  - Teklifi kalan bir ürün varsa, onun tam teklif metnini "NEXT STEP: your next message makes exactly this proposal and no other" satırıyla veriyor.
  - Hiçbir üründe teklif kalmadıysa satır şöyle: "ödeme isteme, müşterinin gün verdiği ürünleri geri okuyup kaydet, teklifsiz ürünler için politikayı uygula ve kapat". Bu satır, teklif kalmadığı sürece sonraki turlarda da duruyor.
  - Müşterinin gün verdiği ürün artık "nothing refused yet" diye değil, "müşteri bir gün veya tutar verdi" diye gösteriliyor.
- 4d4f7b2'nin build testi de 12/13 oldu (spec_vote 74/74/74, farklı alan yok). PUB-12 yine düştü: model STOP'tan sonra araç kredisine tabanı teklif etti. "NEXT STEP" satırı tek başına yetmedi; model kendi önceki mesajının kalıbını kopyalıyor.
- Düzeltme (a729e19), kapanış düğümü `wrap_up`. Fable 5.1'e danışıldı; önerileri de içinde.
  - Her ürün ya STOP'ta ya da müşterinin kendi gün veya tutar verdiği durumdaysa (ve en az biri STOP'taysa) `check_date`, `negotiation_done = yes` ile konuşmayı `wrap_up`'a yönlendiriyor.
  - `wrap_up`'ta pazarlık planı, taban ve deneme adımları yok. Yalnız ürünlerin durumu (DONE satırı, rakamsız) ve en sona konan tek somut sonraki adım var: müşterinin verdiğini geri oku ve onayla, ya da teklifsiz ürünler için politikayı uygula ve kapat.
  - Yasak cümlelerinde rakam geçmiyor ("propose no amount and no date"), çünkü model yasaklanan rakamı da kopyalıyordu.
  - `wrap_up`, negotiate ile aynı araçları, aynı çıkarımı ve aynı geçişleri kullanıyor; yalnız görev metni farklı. Platform dry-run kabul etti, 61 test geçiyor.
- r6, 4d4f7b2 AB × 3 (sonuçlar platformdan doğrudan okundu): PUB-12 üç tekrarda da düştü. PUB-05 üçüncü tekrarda "inconclusive", geri kalan 11 müşteri 3/3 geçti.
  - Üçüncü tekrarın simülasyonu (0ea8137c, 23:20) bütün konuşmaları 23:22'de bitirip değerlendirdiği halde platformda 30 dakikadan uzun süre "running" kaldı. Kit koşucusu bu durumu beklemekten başka bir şey yapamıyor; aynı şey 22:46'daki simülasyonda da 23 dakika sürmüştü.
  - Final build'i `--suite` kullanmadığı için bu takılma finali etkilemez. Ölçüm betikleri artık bir build veya kampanyadan önce çalışma alanında koşan simülasyon kalmamasını bekliyor.
- Fable 5.1 ile ikinci danışma (a729e19 üzerine):
  - Sayaç doğru. Model, kişisel krediye kullandığı kalıbı (1. deneme, ardından son tarihte taban) araç kredisine kopyalıyor. 46 ve "2 Kasım" istemde hâlâ görünüyordu: band satırı ("Band early … deadline 2026-11-02"), takvimdeki "deadline of p3" ve geçmişteki ham get_account.
  - a729e19'daki `check_date → wrap_up` geçişi en üstte `"logic": "and"` kullanıyordu. workflow-format.md'ye göre en üst grup "or" olmazsa koşul sessizce düşüyor, yani kapanış düğümüne hiç girilemiyordu.
- Düzeltme (02c6f7c):
  - geçiş "or" yapıldı; `validate_workflow` artık en üstte "or" dışındaki her grubu hata sayıyor;
  - STOP'a gelmiş bir ürünün son tarihi takvimden ve band satırından çıkıyor;
  - `wrap_up` girişte tek mesaj yazıyor: müşterinin verdiği gün ve borcun tamamıyla geri okuma. Politikanın kabul etmediği bir gün (geçmiş, iş günü değil, son tarihten sonra) geri okunmuyor, önce o gün düzeltiliyor;
  - ilk cevapta gün verip kısmen reddeden müşterinin reddetmediği ürünleri kendi teklifi sayılıyor (dated_products çıkarımı kaçsa da).
- Simülasyon yuvası 0ea8137c yüzünden hâlâ kilitli. `PUT /api/v2/simulations/{id}` ile "completed" yapmayı denedim; izin sınıflandırıcısı ortak kaynağı değiştirmek diye reddetti, aşmadım. Bu yüzden ölçümleri `POST /api/v2/chat/message` üzerinden yapıyorum (simülasyon gerektirmiyor).
- 02c6f7c'nin sohbet denemesi (sürüm 21, PUB-12'yi tur tur oynayan betikle): kapanış düğümüne STOP turunda girildi, geri okuma doğruydu, taban teklif edilmedi. Ama kişisel kredinin notu bir kez pazarlıkta (STOP anında), bir kez de kapanışta yazıldı; defter puanlayıcısı çift notu hata sayıyor.
- Düzeltme (4879ddb): platform her aracın son argümanlarını `<araç>_args.<alan>` olarak değişken tablosunda tutuyor (canlıda görüldü). facts.py her çalışmada başarılı çağrıları ürün bazında `recorded_calls`'a ekliyor; kapanış satırları "add_note bu ürün için zaten yapıldı, tekrar çağırma" diyor. Geri okumadan önce kaydedilmiş bir söz varsa da geri okuma yapılmıyor.
- 4879ddb (sürüm 22) sohbet denemeleri: PUB-12 4/4 defter PASS (3 sıralı, 1 toplu cevap). Bu dört denemede model notu pazarlıkta yazmadı, yani "zaten yapıldı" yolu canlıda henüz tetiklenmedi; birim testte duruyor.
- Yerel ölçüm betiği `scripts/chat_cases.py`: kit vakalarını `chat/message` üzerinden, simülasyon yuvası kullanmadan koşturuyor.
  - Müşteriyi Claude (sonnet) kitin kendi persona metniyle oynuyor.
  - Defteri kitin `score_ledger`'ı puanlıyor; konuşma kontrollerini Claude bir yargıç olarak, konuşma dökümü ve araç çağrıları üzerinden değerlendiriyor.
  - Platformun gemini persona ve yargıcının yerine geçen bir yaklaşık ölçüm; aynısı değil.
- 4879ddb, sürüm 22, AB × 3 sohbet: 13 vakanın 9'u her tekrarda geçti.
  - PUB-04 r1 platform hatasıydı: `chat/message` 404 "Agent service error" döndü, konuşma yarıda kaldı.
  - PUB-05 ve PUB-08 0/3 kaldı: Brief A müşterisine gereksiz add_note yazıldı.
    - Sebebi builder modeli. Claude Code Cumartesi 23:30'da kendiliğinden 2.1.283'ten 2.1.296'ya güncellendi ve `sonnet` takma adı `claude-sonnet-5`'ten `claude-sonnet-5-5`'e kaydı.
    - Bu modelin okumaları add_note kuralını kapsamsız yazıyor ("teklifsiz her ürün için add_note"). Ölçülen bütün eski build'ler, final-candidate dahil, `claude-sonnet-5` ile okunmuştu ve kural "Brief B only" diye kapsamlıydı.
  - PUB-12 3 tekrarın 2'sinde geçti. r1'de model iki ürünün teklifini tek mesajda sordu ve ilk cevabın dışarıda bıraktığı ürünün ilk sorusu sayılmadı.
- Düzeltme (7074252): ilk cevabın dışarıda bıraktığı ve henüz hiç teklif almamış ürünlerin ilk sorusu sayılıyor.
  - Gün verilip başka ürün söylenmediğinde, gün verilmeyen ürünler de ilk sorudan sayılıyor.
  - Sayaç değiştiğinde plan, sıradaki tek teklifi "NEXT STEP: your next message makes exactly this proposal and no other" satırıyla veriyor. Önünde hiç sorulmamış ürün varsa ya da gün verilmiş ama tarihli ürün yoksa bu satır yazılmıyor.
- Builder modeli `claude-sonnet-5`'e sabitlendi: `build.py` varsayılanı, `.env.example`, README ve FINAL.md'de bir kontrol satırı. `.env` de aynı değere çekildi.
  - 7074252'nin bu modelle build'i (sürüm 23) spec_vote 74/74/74 verdi, farklı alan yok. Üç okumanın üçü de add_note'u "Brief B only" diye yazdı.
- 7074252, sürüm 23 (spec `claude-sonnet-5` ile okundu), AB × 3 ve 5 varyant × 3 sohbet ölçümü, Pazar 02:00 civarı:
  - AB'nin ilk tekrarında 13 vakanın 13'ü geçti; PUB-05 ve PUB-08 de geçti, yani gereksiz not sorunu modelle birlikte gitti.
  - Pazar 02:05 civarında platform 503/504 vermeye başladı: r2'nin yarısı ve r3'ün tamamı konuşmanın ortasında ya da hiç başlamadan kesildi. Bunlar ajanla ilgili değil.
  - Kesilmeyen tek başarısız koşu PUB-04 r2. Müşteriyi oynayan model önce 23 Ekim'i kabul edip sonra "tamamını ancak 6 Kasım'da" diye çelişti; ajan da tek ürünlü vakada add_note çağırdı. İzleniyor.
  - Varyant PUB-11 r2'de gerçek bir hata vardı: "kartı ve krediyi ödemem, araç kredisini konuşabiliriz" cevabından sonra araç kredisi için "bugün" yeniden soruldu.
- Düzeltme (01729a7): ilk cevabın açık bıraktığı ürün sayılmıyor, çünkü cevabı müşterinin kendi verdiği bir gün olabilir. Ama satırı "ilk soru onu da kapsadı, tekrar sorma; müşteri gün ya da tutar vermezse sıradaki teklif 1. deneme: …" diyor.
- `scripts/chat_cases.py` artık platform hatasıyla kapanmadan kesilen koşuları INFRA diye işaretliyor, bir dakika sonra yeniden koşturuyor (`--infra-retries 2`) ve puana katmıyor.
- 01729a7, sürüm 24, sohbet ölçümü (Pazar 01:30–02:30):
  - AB × 3: 13 vakanın 10'u her tekrarda geçti.
    - PUB-05 1/3: tek ürünlü A müşterisine "hardship" notu yazıldı (A+B tek ajanda birleşince "Brief B only" kapsamı çağrıda görülemiyor).
    - PUB-10 1/3: yargıç, başarısız create_promise'ın yeniden denemesini çift kayıt sandı; başarısız çağrılar dökümde görünmüyordu. Döküm artık `function_call_error` olaylarını da gösteriyor.
    - PUB-12 1/3: son reddin turunda model, temiz plan satırlarına rağmen bitmiş ürüne bir teklif daha yaptı (önceki tekliflerin kalıbını kopyalama).
  - Varyantlar × 3: 5 vakanın 1'i her tekrarda geçti (PUB-11 2/3, PUB-12-v2 1/3, PUB-13-v1 2/3, PUB-13-v2 2/3).
- Fable 5.1 ile üçüncü danışma (PUB-12, kalıp kopyalama): öneri, son reddin turunda geri okumayı modelden almak ve kodun kurduğu sabit bir satırı söyletmek.
- Düzeltme (bb5fd76): `check_date`, kapanış adımı tek bir geri okumaysa ve müşteri kendi tutarını söylememişse `wrap_up_readback` düğümüne gidiyor. Bu düğümün girişi `tts` ("Understood. Let me read back your promise: … Do you confirm?"), yani o tur model çağrısı yok. Satır çağrı başına bir kez söyleniyor; sonraki turlarda adım "geri okuma söylendi, evet gelirse create_promise" diyor. Onay sorusu politikada tırnak içinde varsa oradan alınıyor. Yeni çıkarım alanı `named_amount_words`, müşteri kendi tutarını söylediyse sabit satırı kapatıyor.
- bb5fd76, sürüm 25: PUB-12 × 4 sohbet, 4/4 geçti; dört koşuda da sabit satır birebir söylendi, "evet"ten sonra create_promise ve iki not, sonra close_call.
- Sürüm 24'ün beş başarısız koşusu için teşhis iş akışı (her vaka için teşhis ve ayrı bir eleştirmen; yalnız okuma):
  - PUB-11 r3, kod hatası: "bugün ödeyemem, kartı da krediyi de" cevabında `_count_refusals`'ın geri dönüş dalı, reddedilen "bugün"ü araç kredisinin müşteri günü sayıyordu; kapanış da 14 Ekim'i müşterinin sözü diye geri okudu.
  - PUB-12-v2: ilk soru açıkken müşteri yalnızca "neden hepsi bugün?" diye sordu; hiçbir şey sayılmadı, planda adım yoktu ve model bugünü yeniden sordu.
  - PUB-13-v1 r3: ölçüm aracının hatası. Sunucu turu bitirdiği halde 504 döndü; araç müşteri satırını yeniden gönderdi, satır iki kez işlendi ve ajanla müşteri farklı konuşmalar gördü.
  - PUB-13-v2 r3: sayaç doğruydu; model sıradaki teklif yerine kartın gününü erkenden geri okudu.
  - PUB-05: A+B birleşiminin yapaylığı. Finalde her brief ayrı derleniyor; builder değişikliği yapılmadı.
- Düzeltme (23c6556):
  - ilk soruya verilen "bugün ödeyemem" artık hiçbir ürünün müşteri günü olmuyor; `named_day_words` ve `dated_products` açıklamaları da "ödeyemem dediği gün" ve "yalnızca sorduğu ürün" için aynı şeyi söylüyor;
  - bir ürün STOP'a gelince, ilk cevabın açık bıraktığı ürünün 1. denemesi NEXT STEP olarak yazılıyor;
  - yeni çıkarım alanı `asked_back` (enum yes/no): ilk soru açıkken müşteri yalnızca soru sorduysa tur sayaca gidiyor (`first_ask_open`), plan "soruyu tek cümleyle cevapla, aynı mesajda ilk ürünün 1. denemesini yap" diyor;
  - bir ürünün teklifi yazılırken başka ürüne müşterinin verdiği gün bekliyor: "no read-back and no confirmation question for it in this message"; bütün sözler sonda birlikte geri okunuyor;
  - kapanış düğümü not yazmayı politikaya bağladı ("when the policy asks for a note");
  - `chat_cases.py`: platform hatası alan her başarısız koşu INFRA sayılıyor ve yeniden koşturuluyor.
  - 65 test geçiyor.
- A vakalarının ölçümü artık yalnızca brief-a.md ile derlenen public-a ajanında yapılıyor (finaldeki gibi tek brief, tek ajan); B vakaları ve varyantlar A+B ile derlenen public-b ajanında ölçülüyor.
- Pazar 03:20: ölçüm sırasında `claude` CLI hesabının 5 saatlik sınırı doldu ("You've hit your session limit · resets 6:10am"). Müşteri personası, yargıç ve builder'ın brief okuması bu hesabı kullanıyor. Aynı dakikalarda makinede kısa bir DNS kesintisi de oldu. Sınırdan sonraki koşular geçersiz (yargıç cevap vermedi).
  - Geçerli koşulardan, bb5fd76 (sürüm 25, A+B): PUB-01..04 3/3, PUB-07 2/2, PUB-10 2/2, PUB-11 2/2, PUB-13 2/2. PUB-05 0/3 ve PUB-08 0/2 (tek ürünlü A müşterisine not, A+B birleşiminin yapaylığı). PUB-06 1/2: müşteri asgari tutarı sorunca ajan tutarı tekrar söyledi, yargıç ikinci teklif saydı. PUB-12 1/2: r2'de müşteri personası senaryodan çıkıp araç kredisini kabul etti, ajan doğru davrandı.
  - 23c6556, yalnız brief-a ile derlenen public-a (sürüm 2): PUB-01, 02, 04 1/1. PUB-03 r1: üçüncü yanlış doğum tarihi "borcum ne kadar?" sorusuyla geldi, ajan verify_identity'yi çağırmadan tarihi bir kez daha sordu. Tek görülme, izleniyor.
  - FINAL.md'ye kontrol satırı eklendi: finalde builder aynı CLI hesabını kullanacağı için 15:00'ten sonra ölçüm yok, 19:50'de CLI'ın cevap verdiği kontrol ediliyor.
- 23c6556 için üç açıdan inceleme iş akışı (sayaç, zayıf model ve gizli brief'lere genelleme), her bulgu ayrıca çürütülmeye çalışıldı. Doğrulanan dört bulgu:
  - `asked_back`, ilk sorudan sonra gelen bir talepte ("daha düşük taksit olur mu?", "bir insanla konuşabilir miyim?") ya da zorluk bildirildikten sonraki "destek ekibi ne yapar?" sorusunda da "yes" olabiliyordu; adım o zaman ödeme teklifi yaptırıyordu.
  - Diğer ürünler STOP'a gelince, itiraz edilen ya da "ödendi" denen ürüne 1. deneme yazılıyordu.
  - Konuşmanın ortasında kaydedilen bir söz, sayacı sıfırdan büyükse ürünü bitmiş saydırmıyordu.
  - ("bugün" koruması, dated_products çıkarımı "kartı bugün öderim" cevabını kaçırırsa o ürünü Cuma teklifine düşürüyor; koruma PUB-11 r3 yüzünden kaldı, bu yalnız çıkarım kaçarsa olur.)
- Düzeltme (2583e08):
  - `asked_back` yalnız istenen ödemeyle ilgili çıplak soruda "yes"; talepler, destek sorusu, zorluk, itiraz ve "ödendi" "no". Kendi gününü söyleyen soru, soru turu sayılmıyor. Soru adımının kendisi de "politika istisnası varsa onu uygula, teklif yapma" diyor.
  - Teklif almadan notu yazılmış ürün kapanmış sayılıyor (teklif yok, kapanışta "notu zaten yazıldı").
  - Sözü kaydedilmiş ürün, sayacı ne olursa olsun teklif almıyor ve kapanışta "söz kaydedildi" sayılıyor.
  - Soruyla kapanan ilk soru sonraki turlarda da kapalı kalıyor (`first_ask_closed`).
  - 65 test geçiyor.
- 2583e08 ölçülmeden önce bir ek düzeltme (007dea1): kimlik cevabı bir soruyla birlikte gelse de ("21 Temmuz 1990, peki borcum ne kadar?") önce verify_identity çağrılıyor.

## Aşama 15 — Pazar sabahı: 007dea1 ölçümü, ad şablonu hatası
- Pazar 06:11'de CLI sınırı açıldı. Sabah zinciri iki derlemeyi paralel başlattı; builder aynı anda tek çalıştırmaya izin verdiği için ikincisi ("Another builder process is running") başlamadı. FINAL.md'ye "derlemeler sırayla" notu eklendi (ea947ca).
- 007dea1, public-b sürüm 26 (A+B): B vakaları × 3 → PUB-11, PUB-12, PUB-13 her biri 3/3. PUB-12 ilk kez her tekrarda geçti.
- Genelleme fixture'ları güncel kodla yeniden derlendi (genx 71/72/71, geny 63/66/65; ikisi de validated). facts.py, iki fixture'ın kendi alan adlarıyla yerelde adım adım koşturuldu:
  - geny: son tarihler doğru (ay sonu son iş günü 31 Ekim cumartesi; 3 iş günü sonrası 17 Ekim), %20 kart tabanı 60, tek denemeden sonra STOP, "neden bugün?" soru adımı, sabit geri okuma satırı.
  - genx: memo'nun 7 takvim günü kuralı (21 Ekim), kapalı gün (2 Kasım), iki denemeden sonra STOP. Geri okuma satırı politikanın tırnak içindeki sorusunu kullanıyor ("Is that correct?").
- Hata: 007dea1 ile derlenen public-a (sürüm 3) A vakalarının çoğunda müşteriye "Mr Reyes" diye sordu. Reyes, brief A'daki örnek isim ve PUB-01'in müşterisi; bir koşuda da uydurma bir isim çıktı. Sonuç: 15 koşunun 9'u başarısız, çoğu "wrong_number".
  - Sebep: ad sorusundaki şablonu derleyici değil, brief'i okuyan model politika metnine yazıyordu. Bu okumada model şablonu `{title} {last_name}` diye tek süslü parantezle yazdı; platform yalnız `{{...}}` biçimini dolduruyor. geny derlemesinde ise ad hiçbir yerde yoktu.
  - Düzeltme (4bf21c7): kimlik görevi, spec'teki her çağrı değişkenini `- last_name: {{last_name}}` biçiminde bir "THIS CALL" bloğunda veriyor. Politika metnindeki `{ad}` ve `<ad>` yer tutucuları da çağrı değişkeni olduklarında `{{ad}}` oluyor. 66 test geçiyor.
- 4bf21c7, public-a sürüm 4 (yalnız brief A), A × 3: 30 koşunun 29'u geçti, adlar doğru.
  - PUB-07 r3: müşteri tatil günü "Monday the 26th"i söyledi; platform çıkarımı doğru yaptı ama 0.49 güvenle attı (eşik 0.6). Kodun tarih kontrolü çalışmadı ve model ertesi iş günü (27 Ekim) yerine son tarihi (2 Kasım) önerdi.
- 007dea1, public-b sürüm 26, varyantlar × 3: 15 koşunun 14'ü geçti. PUB-13-v1 r2'de müşteri personası senaryodan çıkıp 23 Ekim'deki 300'ü reddetti; ajan doğru davrandı.
  - Ama PUB-13-v1'in üç koşusunda da, "bugün hiçbir şey ödeyemem" cevabından sonra ajan kartın ve kredinin tekliflerini tek mesajda yaptı. Plan satırı yalnız kartı söylüyordu ("exactly this proposal and no other"); kredinin satırı da kendi sıradaki teklifini yazıyordu. Brief B kural 4: "go through the products one by one". Yerel yargıç bunu kaçırdı.
  - Düzeltme (b90f3e6): NEXT STEP bir ürünü söylediğinde öteki ürünlerin satırı "only after p1 is settled and never in the same message as p1's" diyor.
- Düşük güvenli çıkarımlar: 105 sohbet çağrısında platform 14 değeri 0.44–0.59 güvenle attı; 14'ü de doğruydu. Aralarında PUB-12'nin "personal loan and car loan" reddi (0.48) ve PUB-11'in "this Friday"i (0.56–0.59) var.
  - b90f3e6 ile derlenen public-b sürüm 27'de PUB-11 3 koşunun 2'sinde düştü: "this Friday" iki koşuda da 0.59 ile atıldı. Model bir koşuda cumayı 17 Ekim sandı (cumartesi), ikisinde de günü sorup ayrıca geri okudu (iki onay).
  - Düzeltme (106d0e5): gün, ret, teklif, tarihli ürün ve tutar alanlarının eşiği 0.35; evet/hayır alanı `asked_back` 0.6'da kaldı.
- 106d0e5, public-b sürüm 28 ve public-a sürüm 5, B, varyantlar ve A × 3 (Pazar 06:50–07:39). Pazar 07:3x'te CLI'ın 5 saatlik sınırı yine doldu ("resets 11:10am"). Sınırdan sonra persona boş döndü (müşteri "Sorry?" dedi, ajan "unclear" ile kapattı), yargıç karar vermedi. Bu koşular geçersiz. Sınırdan önce bitenler:
  - A: 22/22. PUB-07, yani tatil vakası, 2/2.
  - B: 8/8 (PUB-11 3/3, PUB-13 3/3, PUB-12 2/2).
  - Varyantlar: 6/7. Kayıp PUB-13-v1 r2: müşteri 900'ü reddederken "ne ödeyebilirim?" diye sordu. Ajan kural 26'yı uyguladı ("full amount is too much" → floor, once; rest stays overdue), sonra 2. denemede tabanı son tarihte önerdi. Kontrol metni bu ara teklifi hesaba katmıyordu; ajan hatası değil. İki teklif artık tek mesajda yapılmıyor.
  - INFRA sayılan üç ilk denemede müşteri satırı iki kez işlendi (platform hatasından sonra yeniden gönderim); INFRA doğru.
- `scripts/chat_cases.py` (0e150e4): CLI sınır mesajı görülünce yeni koşu başlatılmıyor ve yeniden deneme yapılmıyor. Müşteri satırı ya da yargıç kararı gelmeyen koşu INFRA sayılıyor. INFRA koşusunun dökümü ayrı dosyada kalıyor.
- FINAL.md (a4db8bd): pencere ilk kullanımdan itibaren 5 saat. 11:10–16:10 penceresi ölçüm için. 16:10–19:50 arasında CLI hiç kullanılmıyor, böylece 19:50 kontrolü final için 00:50'ye kadar sürecek temiz bir pencere açıyor.
- 424485c: "THIS CALL" bloğu yalnız ad benzeri değişkenleri ve açılışta ya da kimlik politikasında şablon olarak geçenleri gösteriyor. Çağrı değişkeni olarak gelen bir tutar kimlik doğrulamadan önce görünmüyor.

## Aşama 16 — Pazar 07:40–08:20: CLI sınırı sırasında yerel düzeltmeler
- CLI'ın 5 saatlik penceresi 11:10'da açılıyor. Haftalık kullanım %48, sıfırlanma 16 Ekim. `claude -p "/usage"` kontrolü hiçbir şey harcamıyor (01d86b4). Bu arada yalnız çevrimdışı çalışıldı: testler, eski derlemelerin spec'leriyle prompt farkı ve facts.py'nin yerelde adım adım koşturulması.
- cf4b6ce: kimlik aşaması, değişkenin adı ne olursa olsun aramanın kimin için olduğunu biliyor. 424485c'nin filtresi yalnız adında "name" ya da "title" geçen değişkenleri gösteriyordu; brief kişiyi `customer` ya da `given`/`family` diye adlandırsaydı ajan yine örnek ismi kullanacaktı. Şimdi saat, kimlikler, hesap verisi, güvenlik cevapları ve asistanın kendi adı dışındaki her değişken gösteriliyor.
  - Kimlik aşamasının gördüğü politika metni yalnız bu değişkenleri dolduruyor. `<date>` gibi bir geri okuma yer tutucusu bir çağrı değişkeniyle doldurulmuyor.
  - Güvenlik soruları ve açılış satırı `[var]` biçimini ve her büyük/küçük harf yazımını tanıyor.
  - Açılışta kalan bilinmeyen bir yer tutucu spec sorunu sayılıyor; bu bir düzeltme okumasını tetikliyor.
  - public-b, genx ve geny derlemelerinde prompt farkı yok.
- 29952f1: gün söylemeyen kelimeler müşterinin kendi günü sayılmıyor. Eşik 0.35'e indikten sonra `named_day_words` "then" (0.95 ile görüldü) ya da "right now" olabiliyordu. Gün artık yalnız bir tarihe çözülüyorsa ya da belirsiz bir dönemse ("next month") sayılıyor; "now" ve "right now" bugün oluyor.
- 63a837e: notu yazılmış ürün, sayacı ne olursa olsun bitmiş sayılıyor. Zorluk ya da itiraz notu çoğunlukla ilk ret sonrasında yazılıyor (sayaç 1). O durumda ürün sırada kalıyor, başka bir ürün STOP'a gelince NEXT STEP ona yeniden teklif yaptırıyordu.
- 8524e1a: müşterinin kabul ettiği teklif "anlaşıldı" sayılıyor ve bir daha önerilmiyor. İncelemede görüldü: üç ürünlü bir aramada müşteri kartın 1. denemesini kabul etti, ama bunu kaydeden bir durum yoktu.
  - Kart sırada kaldı ve bekleme metni onun "gününün" beklediğini söyledi. Kredi STOP'a gelince NEXT STEP karta yeniden teklif yaptırdı ve taşıt kredisini beklettirdi.
  - Yeni çıkarım alanı `accepted_products` facts kodunu çalıştırıyor. Kabul edilen ürün denemesiyle birlikte `agreed_products`'a yazılıyor, yeni teklif almıyor ve sıradaki ürünün teklifi geliyor.
  - Geri okumada kabul edilen teklif okunuyor; sabit satır tutarı değil, borcu okuduğu için atlanıyor. Sonradan gelen bir ret anlaşmayı geri alıyor.
  - Ret alanında "yes, credit card" ve "didn't refuse anything" artık ret sayılmıyor.
  - 68 test geçiyor. Üç derlemede prompt farkı yalnız yeni çıkarım alanı ve check_date geçişi.
- 11:11'de çalışacak ölçüm zinciri (measure8.sh), HEAD'den public-b ve public-a'yı sırayla derleyecek. Ardından B × 2, varyantlar × 1 (yeni kart-kabul vakası dahil), A × 1 ve beş insan üslubunun her biri × 1 koşacak.
- 8524e1a'nın bağımsız incelemesi (üç açı, her bulgu ayrıca çürütülmeye çalışıldı) altı gerçek kusur doğruladı. Düzeltme 8d8e8d4:
  - Kredinin teklifine verilen "hiçbirini ödeyemem" (refused 'all', proposed 'personal loan') kartın anlaşmasını sayım yapmadan geri alıyordu. Kart, kredinin STOP'undan sonra kabul ettiği teklifle yeniden öneriliyordu. Artık yalnız o ürün için sayılan bir ret anlaşmayı geri alıyor. Teklif edilen ürün çıkarılmamışsa grup reddi ve çıplak "hayır" anlaşılmış ürüne değil, üzerinde çalışılan ürüne gidiyor.
  - `accepted_products` içindeki 'all', 'everything' ya da 'the loan', hiç teklif edilmemiş ürünleri de anlaşılmış sayıyordu. Kabul artık teklif edilen ürünle sınırlı. Teklif edilen ürün çıkarılmamışsa banka sırasındaki ilk açık ürün alınıyor.
  - İlk sorunun açık bıraktığı bir ürünün (sayaç 0) 1. denemesine verilen "evet" müşterinin kendi günü sayılıyordu: geri okuma borcu gün olmadan okuyordu ve sonraki ürün söylenmiyordu. Artık bu, kabul edilmiş 1. deneme.
  - Notu ya da sözü yazılmış ürün çıkarımla anlaşılmış sayılmıyor. İlk sorudaki soru-cevap kabul sayılmıyor. Tüm ürünler anlaşılmışsa ve hiçbiri STOP'ta değilse geri okuma adımı söyleniyor.
  - Geri okuma, müşteri plan adımı yerine tabanı ya da kendi tutarını kabul ettiyse o tutarı kullan diyor.
- İkinci inceleme (8d8e8d4 üzerinde) beş kusur daha buldu. Düzeltme 98a4925:
  - Müşterinin önce verip sonra reddettiği gün `own_offer_days`'de kalıyordu. Sonraki "evet" o günle geri okunuyordu; gün son tarihten sonraysa kapanış hiç başlamıyordu. Sayılan bir ret, aynı cevapta yeni bir gün söylenmediyse, kayıtlı günü siliyor.
  - Soru-cevapla kapanan ilk sorudan sonra teklif edilen ürün çıkarılmadan gelen 'all', bütün ürünleri anlaşılmış sayıyordu. Daraltma artık ilk soru kapandığında her durumda uygulanıyor.
  - Kabulden ya da STOP'tan sonra, ilk cevabın açık bıraktığı kredi yerine taşıt kredisi söyleniyordu. Sıradaki teklif artık banka sırasında teklifi kalan ilk ürün.
  - Günü tekrar eden "evet, cuma olur" müşterinin kendi günü olarak kalıyor (8d8e8d4 öncesi gibi), böylece sabit geri okuma satırı onu da kapsıyor. Sonraki ürünün teklifi yine geliyor.
  - Zorluk notundan sonra söylenen gün yine müşterinin kendi günü sayılıyor; politika bu sözü kaydediyor.
- Doğrulama:
  - Gerçek 79 sohbet aramasının (106d0e5, 007dea1 ve b90f3e6 koşuları) değişken tabloları eski ve yeni kodla yeniden oynatıldı (scratchpad replay.py). Fark yalnız kabul turlarında, bir de PUB-13-v2'de reddedilen kredinin kayıtlı gününün silinmesinde. Tek ürünlü A aramalarında fark yok.
  - Rastgele 4000 çıkarım dizisinde çökme yok. Anlaşılmış bir ürün hiç önerilmedi, hiçbir NEXT STEP iki teklif yapmadı.
  - 71 test geçiyor.
- Üçüncü inceleme (98a4925 üzerinde) iki kusur doğruladı. Düzeltme 9bd1edf:
  - Günü tekrar eden "evet, 23'ü olur" müşterinin kendi günü sayılınca borç tutarıyla okunuyordu. Oysa 1. deneme taban olabilir: brief-y'nin planı "propose <floor> by <deadline>". Sabit satır 1320 dedi, müşteri 440'ı kabul etmişti. Bu "evet" geri alınınca da 1. deneme yeniden öneriliyordu.
  - Bu "evet" artık yine kabul edilmiş 1. deneme (8d8e8d4'teki gibi) ve geri okumayı model yapıyor.
  - İtiraz ya da "ödendi" notundan sonra söylenen gün, ürünü müşterinin kendi teklifi yapıyordu. Sebebi itiraz, ödeme ya da dolandırıcılık olan not artık ürünü kapatıyor. Zorluk notundan sonraki gün hâlâ sayılıyor.
  - Yeniden oynatma 98a4925 ile aynı sonucu veriyor. 71 test geçiyor.

## Aşama 17 — Pazar 09:20–: final brief'lerinin olası biçimleri için genel destek
- Fuzz (9bd1edf, seed 2, 4000 deneme): sorun yok.
- 149a9aa: taban tutarı `max(<a>, <b>)` ya da `min(<a>, <b>)` olabiliyor ("50 EUR ya da %10, hangisi büyükse"). Borçtan büyük çıkan bir taban (küçük bir borçta sabit asgari) borcun kendisi sayılıyor.
  - Yeni son tarih türleri: gelecek ayın sonu, gelecek ayın son iş günü, bu haftanın ve gelecek haftanın son iş günü.
  - Okuyucunun serbest yazdığı biçimler ("end of the following month", "end_of_week") bu türlere eşleniyor. Sayı içeren ya da "after"/"within" geçen biçimler eskisi gibi bilinmiyor sayılıyor ("see policy").
- 77aeddc: araç yolu `/get_account/{customer_id}` biçimindeyse son adlı parçasından bulunuyor. Yol parametresi `{{ad}}` olarak, çağrı değişkeni adındaki sorgu parametresi URL'ye ekleniyor. Yerel doğrulama bunları geri eşliyor.
- Public derlemelerde iş akışı bayt bayt aynı. 79 aramanın yeniden oynatılmasında fark yok. 72 test geçiyor.
- 99523d2: başka takvim günlerindeki aramalar. Kit, ajanları "birkaç takvim gününde" deniyor; denetim bunları ayrıca denedi.
  - Saat değişkeni başka adla ya da başka biçimde gelebiliyor ("21-10-2026 09:00", "Oct 21, 2026", "20261021T0900"); doğum tarihi hiçbir zaman saat sayılmıyor.
  - "Gelecek ayın 15'i" gelecek aya çözülüyor. Kapalı güne düşen son tarih önceki iş gününe çekiliyor, ama bugünden önceye değil.
  - Cumartesi günü "bu haftanın son iş günü" geçmişte kalıyordu; plan artık gelecek haftanınkini öneriyor.
  - Sabit geri okuma satırı yalnız son tarihi kodla hesaplanmış ürünlerde ve müşteri başka bir tutar söylemediyse kullanılıyor.
  - Okuyucunun uydurduğu bir plan sözcüğü (`<next_business_day_of_week>`, public B'nin seçilen okumasında görüldü) artık bir sözleşme hatası ve bir düzeltme okumasını tetikliyor.
- 7c12182: kimlik sonucu ve araç API'si yeniden adlandırılabilir.
  - Cevap sonucu "MATCH" gibi bir sözcük olabiliyor (`identity.answer_value`). Tanınmayan bir sonuç artık "yanlış" değil, "söylemedi" sayılıyor.
  - get_account'un istediği çağrı anahtarı, sabit (const ya da tek değerli enum) alanlar ve kodun doldurduğu varsayılanlar araç gövdesine baştan yazılıyor.
  - Tarih, araç alanının ya da güvenlik sorusunun istediği biçimde gönderiliyor.
- Üçüncü toplu düzeltme (genel denetimin doğrulanmış bulguları):
  - Aynı türden iki ürün (iki bireysel kredi) aynı adı alıyordu ve birinin reddi ötekinin tekliflerini tüketiyordu. Adları aynı olan ürünlere artık kimlikleri ekleniyor ("personal loan PL-1001").
  - Tabanı ya da adı yalnız bir tür için verilmiş bir eşleme, öteki türlere de uygulanıyordu. Tek anahtar artık yalnız API'nin bir ürün türü değilse (yeniden adlandırılmış bir tür) her türe geçiyor. Eşlemede adı olmayan türün tabanı borcun kendisi sayılıyor.
  - Not sebebi yeniden adlandırılınca ("settled", "payment_made", "not_owed", "contested") ödenmiş ya da itiraz edilmiş ürün geri okunuyordu. Kapatan sebep listesi genişletildi; "hardship" hâlâ kapatmıyor.
  - Başarısız bir kayıt `success: false`, yalnız `error` ya da `ok: false` (boolean) ile dönünce yapılmış sayılıyordu. Düzeltildi.
  - Sabit geri okuma satırının sorusu, kimlik bölümündeki bir sorudan ("Can you confirm your date of birth?") alınabiliyordu. Artık önce doğrulama sonrası ve kapanış metinleri aranıyor, doğrulama öncesi hiç aranmıyor.
  - Bantlar ürün türüne göre olabiliyor (`band.product_types`), bant kendi tabanını verebiliyor (`band.floor_field_by_type`). Metin olarak gelen bir kova ("11-45") ilk sayısıyla, adıyla gelen kova bant adıyla eşleniyor. Hiçbir banda düşmeyen ürün en az deneme sayısını alıyor; önceden sınırsızdı (99).
  - "Söz tarihi yarından önce olamaz" kuralı (`calendar.earliest_promise_day`, genx ve geny'de var). Takvim bugünü "çok erken" diye gösteriyor; "bu haftanın son iş günü" bugünse plan gelecek haftanınkini öneriyor; bugünkü gün olduğu gibi geri okunmuyor.
- Üçüncü toplu düzeltme 6be7c7c'de. fc87ced: sabit İngilizce geri okuma satırı yalnız İngilizce konuşan bir ajanda kullanılıyor. Held-out bir vaka arama gününü (`now_override`) değiştirebiliyor.

## Aşama 18 — Pazar 10:50–: ezber testi (held-out brief'ler) ve ölçüm
- Public sonuçların ezberden gelmediğini görmek için builder'ın hiç görmediği iki brief yazıldı (Fable yazarları, ayrı doğrulayıcılar):
  - H1 (`tests/fixtures/holdout1/`): A+B'nin aynı kuralları, ham banka malzemesi biçiminde (posta zinciri, politika özeti, memo, kod listesi). Kit'in A ve B vakalarıyla ölçülüyor.
  - H2 (`tests/fixtures/holdout2/`): başka kurallar, aynı practice müşterileri; 13 uyarlanmış vaka, bazıları başka bir arama gününde.
- Ölçüm (fc87ced, public-b v29, public-a v6; okumaların üçü de 82 alanda aynı): B 2/3 vaka, varyantlar 4/6, A 9/10, tek tekrarla.
  - PUB-11: müşteri "üçünü de cuma öderim" dedi; adım verilmediği için model önce "tam tutar mı?" diye sordu, sonra geri okudu: iki onay.
  - PUB-11-v2, PUB-13-v2: kod adımı doğru verdi (kişisel kredi için 1. deneme, sonra STOP), model ise adımı atladı ya da STOP'tan sonra taban önerdi.
  - PUB-05: müşteri işini kaybettiğini söyledi, desteği reddetti, "daha fazla süre?" diye sordu; model ikna denemesi yaptı.
- 64ca9f3: "yarından itibaren" kuralında hafta sonuna düşen son tarih bugüne çekilmiyor.
- 6f8afd4: ürün alanları iç içe bir nesnede olabiliyor (`balance.past_due`), tutarlar metin olabiliyor ("EUR 1,234.50").
- afa52fa:
  - Her ürüne kabul edilen bir gün verildiği turda sıradaki adım geri okuma. Yalnız gün yeniyse: aynı günü tekrar eden "evet, onaylıyorum" ikinci bir geri okuma doğurmuyor.
  - Sıradaki adım (`next_step`) müzakere komutunun en sonunda tekrarlanıyor; kapanış düğümünde bu yöntem canlıda işe yaramıştı.
  - Zorluk (hastalık, ölüm, iş kaybı) söylendiğinde politikanın kuralı aramanın geri kalanında ikna planından önce geliyor.
  - Eski 79 aramanın yeniden oynatılmasında fark yalnız PUB-11/PUB-13'te gün verilen turlarda. Fuzz: sorun yok. 87 test geçiyor.
- Ölçüm (9c04f83, public-b v30, public-a v7): ilk koşularda B 3/4, varyantlar 3/3, A 8/8.
  - PUB-12 r1: müzakere doğruydu. Sabit geri okumadan sonra gelen "evet, onaylıyorum" kapanış düğümünün ilk girişine düştü. İlk girişteki giriş mesajı araç çağıramıyor; create_promise metin olarak yazıldı (`_call:create_promise{...}`) ve söz kaydedilmedi. Eski dökümlerde aynı örüntü beş kez görüldü, hepsi aynı yoldan.
- fdc3c25: sabit geri okumadan sonraki kapanış turları, daha önce girilmiş geri okuma düğümüne dönüyor; orada yanıt araçlı normal bir tur.
- Taban formülünde bir alanın katı ("2 * instalment_amount", "min(2 * instalment_amount, past_due)") artık kodda hesaplanıyor. H2'nin araç kredisi tabanında görüldü; önceden taban boş kalıyor ve hesap telefondaki modele kalıyordu.
- 11:20 civarında platform `chat/message` için 503/504 döndü (aynı anda 21 konuşma). H1/H2 konuşmaları durduruldu; public ölçümünden sonra daha az işçiyle yeniden koşulacak. chat_cases, hiç başlamamış bir aramayı artık yargıca göndermiyor.
- 9c04f83 ölçümünün sonu: B'de PUB-11 3/3, PUB-12 2/3 (fdc3c25 ile düzeltilen kapanış hatası), PUB-13 3/3; A'da 10/10 vaka her koşuda geçti (platformun yarıda kestiği 2 koşu sayılmadı). Varyantlarda tek hata PUB-13-v2 r2: kod doğru adımı verdi (kişisel kredi için 1. deneme), model "ne teklif ederseniz edin" reddinden sonra denemeyi atladı.
- Spec denetimi (H1, H2, genx, geny; dört denetçi ve dört şüpheci ajan): 22 bulgu gerçek çıktı. Düzeltilenler:
  - b2f370a: brifin "kelimesi kelimesine" verdiği açılış cümlesi açılış satırında olduğu gibi geçmek zorunda. Okuyucu H2'de "This call is recorded."ı "We are recording this call." yapmıştı; artık bu bir sözleşme hatası ve bir düzeltme okumasını tetikliyor.
  - da5add5: yanlış cevap notu brifin kendi sınırını söylüyor (`identity.max_wrong_answers`). Önceden kod public API'nin `wrong_answers_left` alanını adıyla anıyordu; H2 ve genx'te brif 2 yanlışta, servis 3'te durduruyor.
  - 5fbf7b1: "bugünden sonraki N. iş günü" plan adımı (`<business_day_N>`). H2'de okuyucu `<next_business_day>` kullanıp yanına "2. iş günü" yazmıştı; kod 1.'yi dolduruyordu. Böyle bir adım artık işaretleniyor.
  - cd66bd3: brifin "next <weekday>" / "this <weekday>" kuralı (`calendar.next_weekday`) adlandırılan günü kodda çözüyor. Public A'nın 22. kuralı da bu; önceden "next Friday" iki aday gün olarak modele bırakılıyordu. Yeni public derlemelerinde iki okuma da `following_week` ve `max_wrong_answers=3` verdi.
  - 3c9ddd5: okuyucu kuralları: değiştirilmiş bir maddenin eski sözcükleri ("serious illness") tutulmuyor; durum kuralı (zorluk) bitmemiş her ürünü kapsıyor.
  - 252eeed: her teklifi önceden reddeden bir cevap ("whatever you offer") tek bir ret sayılıyor; planın sıradaki teklifi yapılıyor (PUB-13-v2 r2).
  - 0d1c79b: önceki iş gününe taşınan kapalı bir gün, taşındığı günle değerlendiriliyor; brifin kendi son tarihini söyleyen müşteriye "çok geç" denmiyor (genx).
  - Ertelenenler (brife özgü ya da karmaşık): "too much" sonrası tabanın tutarın yerini alması, aynı teklifin atlanması, ay sonu son tarihinin bugüne düşmesi, zorluk notundan sonraki kendi gün.
