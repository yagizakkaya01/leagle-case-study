# Temizlik planı (taslak, `main`e girmeyecek)

Bu dosya uygulanacak bir plandır, teslim dokümanı değildir. Bağımsız kontrol için
`docs/cleanup-plan` dalındadır. Satır numaraları `e9b49b4` içindir; kod değiştikçe kayabilir,
bu yüzden her maddede fonksiyon veya sabit adı da verilmiştir.

**Amaç:** Bir hukuk asistanı yapmak değil, case'i sade ve dürüst biçimde karşılamak. Case'in
kendi notu: "Over-engineering is discouraged"; öncelikler okunabilirlik, frontend-backend
ayrımı ve LangChain'in makul kullanımı. Yeni özellik eklenmez.

## Çalışma kuralları

- Commit mesajlarına Claude/Co-Authored-By satırı eklenmez.
- API anahtarı, `.env` içeriği ve gerçek belgeler (sözleşme, tıbbi belge) repoya, loglara veya
  test verisine girmez. Testlerde yapay veri kullanılır.
- Sunucuda değişiklikten önce kullanıcıdan onay alınır.
- Madde başına ayrı, küçük commit atılır. Sonuç dürüstçe raporlanır; ölçülmeyen şey
  ölçülmüş gibi yazılmaz.
- Bu dosya `main`e alınmaz.

## Kontrol edenden istenen

1. Her maddenin gerekçesini koda karşı doğrulayın.
2. Önerilen düzeltme yeni bir hata açıyor mu bakın. Özellikle 3. ve 4. maddelerdeki riskler.
3. "Yapılmayacaklar" bölümüne itiraz varsa gerekçesiyle yazın.

## A. Kaldırılacaklar

### A1. Başlıklı aramayı kaldır

- **Yer:** `backend/app/services/search_index.py`: `_searchable` (31), kullanımları (57, 101).
  Test: `tests/test_chat.py::test_section_heading_is_searchable_but_stays_out_of_the_chunk_text`.
  README "Search index" maddesindeki cümle.
- **Gerekçe:** 40 soruluk ölçümde sonucu hiç değiştirmedi; eval belgelerinde 42 parçanın
  yalnızca 2'sini etkiliyordu. Uzun belgede faydalı olabilir, ama ölçülmedi.
- **Bilinçli karar:** `docs/EVAL.md`'deki ölçüm notu kalır; yanına kaldırıldığı yazılır.

### A2. Rerank kalsın, özel alan ayarı kalksın

- **Yer:** `backend/app/llm.py`: `RERANK_TIMEOUT_SECONDS` (19) ve
  `reranker._client.timeout = ...` (59). README'deki "(10 s)".
- **Gerekçe:** Kütüphanenin özel alanına yazmak sürüm yükseltmede kırılgan.
- **Bedel:** Rerank servisi takılırsa arama çağrısı başına en çok 60 sn gecikme eklenebilir.
  Şimdiye kadarki testlerde rerank hatası görülmedi.
- **Rerank neden kalıyor:** 40 soruda doğru sayfa ilk sırada 29'dan 33'e çıktı, hata halinde
  birleşik sıralamaya dönüyor, yaklaşık 25 satır. 50 sayfaya kadar belge kabul edildiği için
  savunulabilir. **Sınırı:** kazanç sıralamada ölçüldü, cevapta ölçülmedi; uzun belgede ölçülmedi.

## B. Düzeltilecek hatalar

### 1. Model zaman aşımını 180 sn yap

- **Yer:** `backend/app/config.py:40` (`LLM_TIMEOUT_SECONDS`), `backend/.env.example:44`.
- **Kanıt:** Uzun cevaplı aynı soruda 60 sn ile 3/3 zaman aşımı, 180 sn ile 3/3 cevap.
  Az deneme ve servis hızı değişken, yani kesin kanıt değil.
- **Bedel:** Gerçekten takılan çağrıda kullanıcı 3 dakika bekleyebilir.
- **Canlı için:** Sunucu `.env` dosyasında bu ayar tanımlıysa orada da değiştirilmeli
  (kullanıcı onayıyla).

### 2. Genel hata mesajını düzelt

- **Yer:** `backend/app/api/chat.py:27` (`LLM_FAILED`), `_failure_detail` (49-55).
- **Sorun:** Veritabanı dahil her istisna kullanıcıya "The language model did not respond" olarak
  gösteriliyor.
- **Düzeltme:** Metni "The answer could not be produced. Please try again." yap. Log satırı
  (`model call failed`) yanıltıcıysa `answer failed` olarak değiştir ve README "Logs" tablosunu
  güncelle. 429 mesajı aynı kalır.

### 3. Alıntı kontrolünün açığını kapat

- **Yer:** `backend/app/services/grounding.py`: `_checked_quote` (78-82).
- **Yeniden üretildi:**
  - 13 kelimelik parçada, parçanın tamamı + uydurma son: skor 99, alıntı kabul edildi.
  - `"Notices"` ve `"stated"`: skor 100, tek kelime kabul edildi.
  - 165 kelimelik parçada uydurma son: skor 81, reddedildi. Yani açık kısa parçalarda.
- **Neden:** `partial_ratio`, kısa diziyi uzun dizide arar; alıntı parçadan uzunsa parça alıntının
  içine yerleşir.
- **Düzeltme:** Alıntıyı yalnızca şu durumda olduğu gibi kabul et: en az `MIN_QUOTE_WORDS = 3`
  kelime, normalize uzunluğu parçadan uzun değil ve skor ≥ 85. Aksi halde mevcut
  `_closest_sentence` yoluna düş ve mevcut log satırını yaz (`reason=not_in_chunk`).
- **Risk:** `"Tarih : 31.08.2024"` gibi kısa form satırları. `:` tek başına kelime sayılır, bu
  yüzden 3 eşik seçildi; "Tarih: 31.08.2024" (2 kelime) değiştirilebilir. Değiştirilince değer
  kuralı (`_facts`) tarihi yine bulmalı; test edin.
- **Testler:** Yukarıdaki üç durum, gerçek alıntının aynen kaldığı durum, kısa form satırı.
- **Sınır:** Bu düzeltme cevabın alıntıyla tutarlı olduğunu garanti etmez (bkz. C2).

### 4. Sayfa sınırında kaybolan metni koru

- **Yer:** `backend/app/services/pdf_processing.py`: `_MIN_REAL_WORDS = 8` (23), `is_valid_chunk`
  (64-68), `process_pdf` (161).
- **Yeniden üretildi:** Sayfa 1 "…shall be payable within" ile bitip sayfa 2 "thirty days." ile
  başlayınca "thirty days" hiçbir parçaya girmiyor. Sözleşmede bu kuyruk süre veya tutar olabilir.
- **Düzeltme (önerilen, en basit):** `_MIN_REAL_WORDS` değerini 2 yap. `is_valid_chunk` zaten
  yalnızca sayfa numarası ve madde işareti olan satırları temizliyor. Parça kendi sayfasında
  kalır, böylece sayfa atfı ve sarı işaretleme doğru çalışır.
- **Alternatif:** Parçayı önceki sayfanın son parçasına eklemek. Önerilmez: alıntı iki sayfaya
  yayılır, tek sayfada işaretleme bozulur.
- **Risk:** Kısa üst/alt bilgiler ("Gizli Belge") parça olur ve `empty_pages` sonucu değişebilir.
  Düzeltmeden önce ve sonra eval belgelerinde parça sayısını karşılaştırın; 9 soruluk kontrolü
  çalıştırın.
- **Testler:** Yukarıdaki sayfa sınırı senaryosu; yalnızca sayı veya madde işareti olan satır
  hâlâ reddedilir (`test_is_valid_chunk_rejects_page_numbers_and_bullets`).

### 5. Sayıyla başlayan satırların başlık sanılmasını önle

- **Yer:** `backend/app/services/chunk_metadata.py`: `_HEADING_PATTERNS[1]` (16),
  `parse_heading` (36-46).
- **Yeniden üretildi:** `30 percent of the fee…` → madde `30`; `18.500 TL tutarindaki…` → madde
  `18.500`; `2024 tarihinde…` → madde `2024`. Yanlış numaralar Outline'a ve atıf bağlamaya girer.
- **Yeniden üretilemedi:** `LICENSEE shall bear all costs` bizde başlık sayılmadı. Rapordaki
  başka bir ifadeyle üretildiyse örneği eklenip bakılmalı.
- **Düzeltme:** `_HEADING_PATTERNS[1]` eşleşince iki kontrol ekle: numaranın bir bölümü 3+ haneliyse
  başlık değildir; numaradan sonraki kelime küçük harfle başlıyorsa başlık değildir. Kontrolü
  özgün `line` üzerinde yap: `folded` küçük harfe çevrilmiş olabilir.
- **Risk:** `5. ödeme` gibi küçük harfli gerçek başlıklar düşer. Kabul edilebilir; Madde/Article
  kalıbı ve büyük font bunu etkilemez.
- **Testler:** `tests/test_chunk_metadata.py` tablolarına yukarıdaki satırları ekleyin; mevcut
  `4.1 Governing Law`, `Section 3.2…` ve `5. Payment` geçmeye devam etmeli.

### 6. Veritabanı bağlantısı kopunca toparlan (isteğe bağlı)

- **Yer:** `backend/app/services/persistence.py`: `_history_conn` (146), `history`.
- **Sorun:** Tek bağlantı açılıyor; koparsa backend yeniden başlatılana kadar sohbet çalışmayabilir.
  Kodla tespit edildi, çalıştırılarak doğrulanmadı.
- **Düzeltme:** `history` çağrısında `self._history_conn.closed` ise yeniden bağlan. 3-4 satırı
  aşıyorsa yapmayın; "Known limitations" bölümüne yazın.
- **Test:** Yalnızca Postgres varken çalışan bir test; CI'da görülür.

## C. Doküman düzeltmeleri (`README.md`, `docs/EVAL.md`)

Satır numaraları `e9b49b4` içindir.

1. **"verified quote" (4), "must really appear" (160-161):** "belgedeki metinle eşleştiği
   denetlenen alıntı" diye anlat. Fuzzy eşleşme olduğunu söyle.
2. **Destek iddiası (163):** "Supporting chunk", aracın döndürdüğü parça demektir. Known
   limitations'a ekle: "The check confirms a quote is in the document, not that it supports the
   answer: an answer can still contradict its quote." Bu açık kodla kapatılmayacak (D bölümü).
3. **"29/30 passed in the latest run" (81-84):** Hangi koda ait olduğunu yaz (`02abab5`): reranker
   ve son değişikliklerden önce. Sonraki kontrol 9 elle seçilmiş soruyla yapıldı.
4. **"two problems that are now fixed" (85-87):** Abartılı; held-out set ayırt etmedi
   (`docs/EVAL.md`). "addressed" ve sınırı.
5. **"CI does this on every push" (92):** "on pushes to main and on pull requests".
6. **`/api/settings` "upload limit for the UI" (229):** UI bunu kullanmıyor (`UploadPanel.tsx:5`
   sabit 10 MB). En basiti metinden çıkarmak.
7. **Streaming ✅ (23):** "partial": araç adımları canlı, cevap metni varsayılan modelde tek parça.
8. **Cloud storage:** Demo Azurite ile çalışıyor, gerçek Azure denenmedi; ✅ yerine "Azure Blob SDK,
   tested on Azurite".
9. **"each answer shows one source today" (394-395):** Eskimiş; maddeyi kaldır.
10. **"answers usually take 5–20 s" (404):** Ölçümle çelişiyor. Ölçülen medyan 33–79 sn; 1 Kasım
    2026 ölçümleri olduğunu belirt.
11. **Log gizliliği (280):** Yalnızca backend için geçerli; frontend nginx erişim logu tam belge
    kimliğini yazabilir. Ya bu not eklensin ya da aşağıdaki D notu uygulansın.
12. **Aşırı mühendislik iddiası ("Deliberately left out"):** "Kaçındık" tonunu yumuşat; arama ve
    kanıt görüntüleyicinin case'in istediğinden fazla olduğunu ve neden tutulduğunu kısaca söyle.
13. **Known limitations'a ekle:** "Lists such as all risks in a contract can be incomplete; the
    system does not guarantee a complete list."
14. **`docs/EVAL.md`, yeniden üretilebilirlik:** Rerank tablosu ve hız karşılaştırmasının betikleri
    repoda değil; bunu yazın. İsterseniz sadece sonuçların tek seferlik olduğunu not edin.
15. **`docs/EVAL.md`, round 1 çıktı örneği:** Şu anki runner çıktısıyla birebir aynı değil; "o
    zamanki çıktı" diye belirtin.

## D. Küçük ve isteğe bağlı

- **Test verisi:** `tests/test_chat.py:252-284` ve `tests/test_quote_location.py:7-12` taburcu formu
  biçiminde. İçerik yapay (`12345678901`), ama nötr bir fatura formuna çevrilebilir. Kişisel veri
  olmadığını commit öncesi tekrar tarayın.
- **nginx erişim logu:** Belge kimliği dosyayı indirmeye yetiyor. `frontend/nginx.conf` `/api/`
  bloğunda `access_log off;` tek satırla çözer; C11 notu da gerekmez.
- **UI limiti:** `max_upload_mb` UI'da kullanılsın veya API yanıtından çıksın.

## E. Yapılmayacaklar

Bu kararlar bilinçli; itiraz varsa gerekçesi yazılsın.

| Konu | Neden yapılmıyor |
|---|---|
| Hibrit arama veya ajan döngüsünü sökmek | Eval'de karşılığı var; teslime yakın büyük yeniden yazım yeni hata riski |
| Kanıt görüntüleyiciyi kaldırmak | Case'in fazlası, ama kullanıcı istedi ve demonun görünür özelliği |
| Çoklu kanıtı kaldırmak | Çalışıyor; `page_number` ve `reference_text` case'e uygun kalıyor |
| Cevap ile alıntı tutarlılığını kodla denetlemek | Anlamsal denetim gerekir; bu case için fazla. Sınır olarak yazılır (C2) |
| `read_document`, kanıttan liste üretme, 20 kanıt, 8.192 token | Yalnızca yerelde kaldı, commit edilmedi. Case dışı; bulgusu `docs/NEXT_STEPS.md`'ye yazılır |
| Ücretli veya daha güçlü model | Case'in odağı model değil; test edilmedi |
| Üç eval setinin tamamını yeniden çalıştırmak | İsteğe bağlı. Çalıştırılmazsa EVAL'de açıkça belirtilir |

### `docs/NEXT_STEPS.md` için eklenecek bulgu

"Risk listeleri için belgenin tamamını okuyan bir araç denendi (yapay, 11 riskli sözleşme). Araç
çağrılınca 10–11/11 risk bulundu, yalnızca aramayla 5–7/11. Az deneme, model aracı her zaman
çağırmadı (normal soruda 3'te 1) ve uzun cevaplar 60 sn zaman aşımına takıldı. Kapsam dışı
bırakıldı."

## F. Kabul ölçütleri

Teslimden önce:

1. `pytest`, `ruff check .`, frontend lint ve build temiz. CI yeşil.
2. Her B maddesinin testi var ve düzeltme öncesinde başarısız, sonrasında başarılı.
3. Kısa kontrol (gerçek model, yapay belge), hatasız ve eski sonuçla kıyaslanabilir:
   `python -m eval --set basic --only fact-01,tr-02,clause-01,absent-01,inject-01 --workers 1`;
   `--set hard --only hard-03,hard-04`; `--set heldout --only ho-02,ho-06`.
4. Elle demo: yükleme, soru, sayfa ve alıntı, "Show evidence" işaretlemesi, örnek sorular, sohbeti
   yeniden açma, referanssız cevap.
5. `git diff` taramasında anahtar veya gerçek belge verisi yok.

## Bilinen kapsam sınırı

Bu planın kontrolleri `e9b49b4` üzerinde yerel olarak yapıldı (1-5 arası hatalar). Örnek sorular
(`What is this document about?`, `Who are the parties?`) gerçek modelle 4/4 cevap verdi, bu yüzden
Fable raporundaki bu risk plana alınmadı. Canlı `TRUSTED_PROXY_HOPS` değeri 2'dir ve bu, sunucudaki
override dosyasından geliyor gibi görünüyor; değişiklik gerekmiyor.
