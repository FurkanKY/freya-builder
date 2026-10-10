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
