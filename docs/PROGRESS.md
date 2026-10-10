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
