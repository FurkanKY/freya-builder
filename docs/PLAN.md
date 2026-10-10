# Freya Builder Implementation Plan — Revizyon 2

> Yürütme: superpowers:executing-plans; aynı sohbette doğrudan uygulama. Kullanıcı uygulamayı başlattı. Önceki 9 görevli plan work/plan-archive-v1 altında arşivlendi; yürütülecek plan budur.

**Goal:** Brief ve onun API şemasından çalışan Freya workflow’u, export ve trace üretmek; uygun testlerle en fazla bir otomatik düzeltme döngüsü yapmak.

**Architecture:** Python koordinatör + araçsız Claude Agent SDK çağrısı + Freya istemcisi. Ham girdiler ve kaynaklı kapsam listesi; iki aday slotu; açık suite seçimi; toplam deadline.

**Tech Stack:** Python 3.12, Claude Agent SDK, jsonschema, python-dotenv, pytest. Çalışan bağımlılıklar requirements.lock dosyasında sabitlenecek.

**Spec:** [Mimari tasarım](2026-10-10-freya-builder-design.md), Revizyon 2 kararları önceliklidir.

## Global Constraints

- Brief başına toplam süre en fazla 1800 saniye; finalize rezervi 120 saniye.
- Telefon ajanı modeli kit’teki AGENT_LLM; değiştirilmez.
- Bir workspace aynı anda bir simülasyon. Test için belgelenmiş suite dışında endpoint tahmin edilmez.
- Sırlar loglara, modele veya commit’e aktarılmaz.
- Model yalnızca JSON üretir; araç, shell ve kullanıcı dosyalarına erişmez.
- Çalışan snapshot korunur; final export seçilen ve test edilen adayla bağlanır.
- Başarılı ledger testi olmadan davranış puanı verilmez.

## Review Focus

- Yanlış API girdisi/suite: input fingerprint ve public brief eşleştirme testi.
- Testten önce süreç bitmesi: deadline ve izlenen subprocess testi.
- Yanlış adayın export edilmesi: iki slot/checkpoint testi.
- Bilinmeyen kayıt sonucu: açık hata ve timeout ayrımı.
- Secret leakage: log ve model girişinde redaction testi.

## Görev 1 — Ortam ve erişim

Files: vendor/kit-v3, .env.example, requirements.lock, pyproject.toml, docs/PROGRESS.md.

- [ ] Salt okunur kit snapshot’ı ve manifest, özel .env, geliştirme branch’i oluştur.
- [ ] Python ortamı ve SDK kur; sürümleri sabitle.
- [ ] Claude Code oturumundan araçsız küçük SDK çağrısını doğrula.
- [ ] Freya workspace erişimini read-only doğrula; anahtarları yazdırma.
- [ ] Ortam raporu ve Git başlangıç commit’i; ilerleme kaydı.

## Görev 2 — Tek komut ve ilk workflow

Files: builder/build.py, builder/runtime.py, builder/generate.py, builder/freya_client.py, tests/test_runtime.py, tests/test_generation.py, tests/test_client.py.

Interfaces: Budget.remaining(), Budget.require(seconds); load_inputs(briefs, api); generate(inputs, budget, trace) -> dict; Client.validate(workflow), Client.publish(slot, workflow), Client.export(workflow_id).

- [ ] Kritik testleri yaz ve başarısız olduklarını gör: farklı API dosyası kullanımı, rezervi ihlal eden çağrı, sır redaction, tool kullanımının kapalı olması, eksik node hedefi.
- [ ] CLI hem --brief/--tool-api hem iki pozisyonel argümanı tek koda normalize etsin; --slot isteğe bağlı.
- [ ] Ham brief + OpenAPI + kit docs + base workflow üzerinden kaynaklı kural/kapsam ve workflow JSON’u üret.
- [ ] Yapı, kod sözdizimi, node referansları, araç host/alanları için dar doğrulama; ardından Freya dryRun.
- [ ] Workflow’u oluştur/yayımla; gerçek platform export’unu ve trace’i kaydet.
- [ ] Testleri geçir, bir küçük canlı uçtan uca deneme yap, commit ve ilerleme kaydı.

## Görev 3 — Baseline ve resmi değerlendirme

Files: builder/evaluate.py, tests/test_evaluate.py, runs/.

Interfaces: run_cases(agent_id, suite, budget) -> report; get_failure_evidence(report) -> list.

- [ ] Public A/B girdisi eşleştirme ve 2/3 tekrarın başarı sayılmaması testlerini yaz/çalıştır.
- [ ] Resmî runner’ı yazılabilir kit kopyasından çalıştır; --out, --only ve --reps destekle.
- [ ] A ve A+B’den ayrı ajanlar üret; önce tek tur baseline. Üç tekrar ve stiller sadece bütçeli geliştirme kampanyasında.
- [ ] Çalışan süreç ve sunucu simülasyonu durumunu ayır. Deadline ile iptal edilen istemciyi bitmiş simülasyon sayma.
- [ ] Test skoru, sürüm, konuşma kayıtları, hata nedenleri; commit ve ilerleme kaydı.

## Görev 4 — Kanıtlı düzeltme ve iki slot

Files: builder/build.py, builder/generate.py, tests/test_selection.py.

- [ ] Testleri yaz: farklı suite karşılaştırılamaz; kötü aday iyi slotu ezmez; export seçilen adaya aittir.
- [ ] Aynı suite/tekrar/stil üzerinde karşılaştır; karşılaştırılabilir kanıt yoksa incumbent’ı koru.
- [ ] En fazla bir repair + retest, sadece yeterli zaman varsa. Static schema hatası düzeltmesi de aynı bütçeye tabi.
- [ ] Varsayılan model serbest kod değiştirmez; yalnızca aday JSON’unu üretir. Scorer/test beklentileri değişmez.
- [ ] Başarılı export’ları yerel checkpoint yap; testleri geçir; commit ve ilerleme kaydı.

## Görev 5 — Kritik platform deneyleri ve kararlılık

Files: tests/test_policy.py, runs/, üretim prompt’larının ilgili bölümleri.

- [ ] Aynı ifade ve farklı now değerleriyle tarih çapasını kontrol et; belirsiz ifadeyi otomatik kesin tarihe dönüştürme.
- [ ] Parametre baking, customer correction sonrası re-entry, çok ürünlü kayıt ve tek kapanışı küçük vakalarda kontrol et.
- [ ] Yalnızca kanıtlanan eksikleri düzelt; tam doğal dil parser’ı ve yeni kayıt motoru peşinen yazılmaz.
- [ ] Public A/B üç tekrar ve seçili stiller; kimlik/enum/memo için üç yerel genelleme fixture’ı.
- [ ] Bilinmeyen davranışları başarı sayma; commit ve ilerleme kaydı.

## Görev 6 — Tekrar üretim ve teslim

Files: README.md, requirements.lock, submission/.

- [ ] Temiz ortamdan aynı CLI ile çalıştır; önceki run state’i zorunlu olmasın.
- [ ] Test edilen model/sürüm ile seçilen export/trace’i eşleştir; node ve araç sayısı, export hash’i kaydet.
- [ ] Sır taraması yap; export’u körlemesine değiştirme.
- [ ] Son bağımsız kod incelemesi, kritik düzeltmeler ve yerel testler.
- [ ] Son duyurudaki teslim sözleşmesini teyit et. Gizli brief’lerde yalnızca runtime girdi kullan.

## Zaman kapıları ve kesme sırası

- İlk erişim denemesi bu çalışma içinde. Erişim yokken yerel uygulama/test devam eder; key eksikliği varsa kullanıcıya bildirilir.
- İlk çalışan export elde edilmeden gelişmiş mimari eklenmez.
- Cumartesi gece yarısı: A/B export ve trace yoksa özellik ekleme durur, mevcut akış düzeltilir.
- Pazar gizli brief’ler açılmadan: çalışan commit sabitlenir ve teslim provası yapılır.
- Önce kesilecekler: geniş stil matrisi, ek mutasyonlar, yeni parser/kayıt motoru, bütçeye sığmayan repair. Kesilmeyecekler: gerçek girdiler, deadline, doğru export, trace, sır koruması.

## Süreklilik

Her aşamadan sonra outputs/ILERLEME.md ve docs/PROGRESS.md güncellenir: tamamlanan, test kanıtı, commit, açık sorun, sıradaki komut. Aktif run kimliği kaydedilir. Yeniden başlayan ajan öncelikle bu dosyayı ve git log’u okur; canlı simülasyonu kontrol etmeden yenisini başlatmaz.
