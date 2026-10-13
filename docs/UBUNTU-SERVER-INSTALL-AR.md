# تثبيت خادم FG MTM على Ubuntu

الدليل ده لمشغّل السيرفر: تجهيز قاعدة البيانات وAPI وعامل المزامنة ولوحة التحكم، ثم ربط البرنامج بحساب المؤسسة والفرع.

**المسار المقترح: Ubuntu 24.04 LTS، Docker Engine وCompose، ودومين فرعي عليه HTTPS.** تحتاج صلاحية sudo ووصول SSH. الخادم اختياري؛ إدارة الراوتر محليًا لا تتطلب تشغيله.

> الملفات الحالية مسار تطوير قابل للنشر والاختبار، وليست إصدار خادم إنتاج معتمد باختبارات سعة. اختبر الدخول والمزامنة والنسخ الاحتياطي قبل الاعتماد عليه لشغلك. الـAPI ليس خادم RADIUS UDP؛ تشغيل RADIUS مع MikroTik يحتاج إعداد FreeRADIUS منفصل.

## 1. جهّز عنوان السيرفر

اعمل سجل DNS من نوع A للدومين الفرعي، مثل `mtm.your-domain.com`، يشير إلى IP السيرفر. لو فيه سجل AAAA، لازم عنوان IPv6 يكون صحيحًا وقابلًا للوصول. المثال في الأوامر ليس دومينًا جاهزًا لك.

افتح TCP 80 و443 في جدار مزوّد السيرفر. احتفظ بمنفذ SSH الفعلي مفتوحًا. لا تفتح 8080 أو 5432 للعامة؛ قاعدة البيانات داخل شبكة Docker، وAPI على loopback فقط.

لو UFW مفعّل بالفعل، أضف القواعد دي؛ لا تفعّل UFW من جلسة بعيدة قبل مراجعة منفذ SSH:

```bash
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw status
```

منافذ Docker المنشورة قد تتجاوز قواعد UFW؛ راجع جدار مزوّد السيرفر وقواعد Docker أيضًا.

## 2. ثبّت الأدوات وDocker

لو Docker وCompose شغالين بالفعل، احتفظ بهما واكتفِ بفحص النسخة. لا تستبدل Docker المستخدم في مشروعات قائمة عشوائيًا.

```bash
sudo apt update
sudo apt install -y ca-certificates curl git python3 iproute2
sudo docker version
sudo docker compose version
```

لو Docker غير مثبت، على سيرفر جديد نفّذ:

```bash
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo docker run --rm hello-world
sudo docker compose version
```

لو عندك حزم Docker متعارضة، اتبع [دليل Docker الرسمي](https://docs.docker.com/engine/install/ubuntu/) قبل التثبيت؛ لا تحذف خدمة مستخدمة بدون مراجعة.

## 3. نزّل ملفات الخادم الفعلية

صفحة FG Machines هي صفحة التوزيع والشرح. مصدر الخادم العام حاليًا موجود في `nexvary/FG-MikroTik-Manager`. الأوامر التالية تنزّل نسخة محددة تمت مراجعة أوامر تشغيلها، ولا تحتاج رابط حزمة أو حساب GitHub خاص:

```bash
git clone --branch dev/product-family --single-branch https://github.com/nexvary/FG-MikroTik-Manager.git fg-mtm-source
cd fg-mtm-source
git checkout --detach 9f6e5e34f6e8754e43d282df4d225b942fbd2b94
cd server
bash -n scripts/start-ubuntu.sh
```

الأوامر التالية كلها من مجلد `fg-mtm-source/server`. لو المجلد موجود من تثبيت سابق، لا تبدأ تثبيتًا جديدًا فوقه؛ راجع قسم التحديث.

## 4. اختار طريقة النشر

| حالة السيرفر | المسار |
| --- | --- |
| سيرفر جديد ومنافذ 80 و443 و8080 فاضية | المسار A: Caddy من الحزمة |
| سيرفر عليه Nginx أو مواقع أو خدمات قائمة | المسار B: API محلي ودومين مستقل على Nginx |
| سيرفر عليه proxy آخر | شغّل Compose الأساسي فقط، واربط proxy الحالي بـ127.0.0.1:8080 |

افحص المنافذ أولًا:

```bash
sudo ss -ltnp '( sport = :80 or sport = :443 or sport = :8080 )'
```

### المسار A — سيرفر جديد

استبدل الأربع قيم: الدومين، معرّف المؤسسة، معرّف الفرع، واسم حساب الخادم.

**لو عندك بيانات قائمة في التطبيق، خُد المؤسسة والفرع حرفيًا من صفحة مزامنة الخادم.** لا تستخدم أسماء تجريبية بدل المعرّفات. في تثبيت جديد بالكامل يمكنك تحديد نطاقك، ثم استخدام مسار ضم السجل الفارغ المدعوم في التطبيق.

```bash
sudo bash scripts/start-ubuntu.sh mtm.your-domain.com TENANT_ID BRANCH_ID owner
```

السكربت يولّد كلمة مرور عشوائية لقاعدة البيانات ويحفظها في `.env` بصلاحيات خاصة، ثم يبني الخدمات ويطلب كلمة مرور المالك مرتين. استخدم 12–128 حرفًا؛ كلمة المرور لا تُكتب ضمن الأمر ولا تظهر أثناء الإدخال.

لو السكربت توقف بعد إنشاء `.env`، لا تحذفه لتعيد التجربة؛ راجع السجلات. لإكمال تشغيل الحزمة وإنشاء الحساب إذا لم يُنشأ بعد:

```bash
sudo docker compose -p fg-mtm -f compose.yml -f compose.https.yml up -d --build
sudo docker compose -p fg-mtm -f compose.yml -f compose.https.yml run --rm api python -m fg_server account --tenant TENANT_ID --branch BRANCH_ID --username owner --role owner
```

الحساب الموجود بالفعل لا يُستبدل بهذا الأمر. هذا المسار يستخدم Caddy الافتراضي الموجود بالمصدر؛ أضف تحديد معدل الطلبات عند بوابة الوصول قبل فتحه لجمهور عام، أو استخدم مسار Nginx التالي الذي يتضمن ذلك.

### المسار B — سيرفر عليه Nginx

لا تشغّل `compose.https.yml` هنا؛ حتى لا تتعارض حاوية Caddy مع المواقع الموجودة. لازم منفذ 8080 يكون فاضيًا، أو تعدّل منفذ المضيف في `compose.yml` وتستخدم نفس الرقم في proxy.

أنشئ `.env` مرة واحدة. الأمر يرفض الكتابة فوق ملف موجود:

```bash
sudo python3 - <<'PY'
from pathlib import Path
import os
import secrets
path = Path(".env")
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w") as file:
    file.write("FG_DB_PASSWORD=" + secrets.token_hex(32) + "\n")
PY
sudo docker compose -p fg-mtm -f compose.yml config --quiet
sudo docker compose -p fg-mtm -f compose.yml up -d --build
sudo docker compose -p fg-mtm -f compose.yml run --rm api python -m fg_server account --tenant TENANT_ID --branch BRANCH_ID --username owner --role owner
```

جهّز Nginx وCertbot لو مش موجودين:

```bash
sudo apt install -y nginx certbot python3-certbot-nginx nano
```

افتح الملف الجديد، والصق المحتوى التالي ثم احفظ بـCtrl+O ثم Enter واخرج بـCtrl+X:

```bash
sudo nano /etc/nginx/conf.d/fg-mtm-rate-limit.conf
```

المحتوى داخل سياق http:

```nginx
limit_req_zone $binary_remote_addr zone=fg_mtm_login:10m rate=5r/m;
```

وافتح ملف موقع جديد، ثم الصق الإعداد التالي بعد تغيير الدومين واحفظ بنفس الطريقة. لا تستبدل ملف موقع موجود:

```bash
sudo nano /etc/nginx/sites-available/fg-mtm
```

```nginx
server {
    listen 80;
    server_name mtm.your-domain.com;
    client_max_body_size 21m;

    location = /v1/login {
        limit_req zone=fg_mtm_login burst=5 nodelay;
        limit_req_status 429;
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 60s;
    }
}
```

ثم فعّل الموقع واختبر الإعداد قبل إعادة التحميل، واطلب شهادة الدومين:

```bash
sudo ln -s /etc/nginx/sites-available/fg-mtm /etc/nginx/sites-enabled/fg-mtm
sudo nginx -t
sudo systemctl reload nginx
sudo certbot --nginx -d mtm.your-domain.com --redirect
sudo certbot renew --dry-run
```

لا تدخل كلمة مرور اللوحة عبر HTTP قبل صدور الشهادة. لو السيرفر خلف CDN/proxy إضافي، اضبط عناوين المصادر الموثوقة قبل الاعتماد على تحديد معدل الطلبات حسب IP.

## 5. تأكد إن التشغيل سليم

للمسار A:

```bash
sudo docker compose -p fg-mtm -f compose.yml -f compose.https.yml ps
sudo docker compose -p fg-mtm -f compose.yml -f compose.https.yml logs --tail=100 api worker db caddy
curl --fail --show-error https://mtm.your-domain.com/health
curl --fail --show-error --output /dev/null https://mtm.your-domain.com/panel/
```

للمسار B، احذف `-f compose.https.yml` من أوامر Compose، ولا تذكر خدمة `caddy`.

`/health` يرجع JSON فيه `version`؛ ده اختبار وصول للـAPI وليس فحصًا كاملًا لقاعدة البيانات والمزامنة.

افتح **https://mtm.your-domain.com/panel/** وسجل دخولك. شغّل تشخيص الخادم، ثم جرّب مزامنة حقيقية من التطبيق وراجع السجلات والفرع. لا تستخدم `curl -k` لإخفاء خطأ شهادة HTTPS.

## 6. اربط Android أو Windows

| الحقل | القيمة |
| --- | --- |
| عنوان الخادم | `https://mtm.your-domain.com` بدون `/panel/` |
| المؤسسة والفرع | نفس المعرّفات التي أنشأت الحساب بها |
| اسم المستخدم وكلمة المرور | حساب الخادم، وليس حساب MikroTik |

راجع نطاق البيانات، واضغط المزامنة واقرأ النتيجة. حساب واحد له جلسة واحدة؛ دخول جديد يلغي الجلسة القديمة. للاستخدام المتزامن على اللوحة والتطبيق أنشئ حسابًا آخر بنفس المؤسسة والفرع واسم مختلف:

```bash
sudo docker compose -p fg-mtm -f compose.yml run --rm api python -m fg_server account --tenant TENANT_ID --branch BRANCH_ID --username panel-owner --role owner
```

لو تستخدم المسار A أضف `-f compose.https.yml` بعد `-f compose.yml`.

## 7. النسخ الاحتياطي والتحديث

احفظ `.env` بصورة خاصة خارج السيرفر؛ يحتوي بيانات قاعدة البيانات. لا ترفعه إلى GitHub. للنسخ الاحتياطي في المسار A:

```bash
umask 077
sudo docker compose -p fg-mtm -f compose.yml -f compose.https.yml exec -T db pg_dump -U fgmtm -Fc fgmtm > "fgmtm-$(date -u +%Y%m%d-%H%M%S).dump"
```

تأكد أن الملف غير فارغ، وانقل نسخة إلى مكان آمن واختبر الاستعادة في قاعدة منفصلة قبل الاحتياج لها. في المسار B احذف ملف HTTPS من الأمر.

عند إصدار نسخة مصدر جديدة، راجع التغييرات وSHA المقصود أولًا. احتفظ بنفس مجلد التشغيل وملف `.env` واسم المشروع `fg-mtm`. بعد النسخة الاحتياطية:

```bash
cd ..
git fetch origin dev/product-family
git checkout --detach NEW_REVIEWED_COMMIT_SHA
cd server
sudo docker compose -p fg-mtm -f compose.yml -f compose.https.yml build
sudo docker compose -p fg-mtm -f compose.yml -f compose.https.yml stop api worker
sudo docker compose -p fg-mtm -f compose.yml -f compose.https.yml run --rm migrate
sudo docker compose -p fg-mtm -f compose.yml -f compose.https.yml up -d
```

استبدل `NEW_REVIEWED_COMMIT_SHA` بالنسخة التي قررت نشرها. لا تنفذ بقية الأوامر إذا فشل البناء أو الترحيل. في المسار B احذف ملف HTTPS. **لا تستخدم `down -v`؛ يحذف وحدات تخزين البيانات.**

قاعدة البيانات في Compose الحالي لا تحتوي سياسة إعادة تشغيل. لتشغيلها تلقائيًا بعد إعادة تشغيل السيرفر:

```bash
sudo docker update --restart unless-stopped "$(sudo docker compose -p fg-mtm -f compose.yml ps -q db)"
```

كرر ذلك بعد إعادة إنشاء حاوية قاعدة البيانات. بعد أي إعادة تشغيل أو تحديث، راجع `ps` والدخول والمزامنة.

## أوامر احتياطية وإدارة المؤسسة والفرع

الأوامر دي لمسؤول عنده SSH وصلاحية sudo على السيرفر. لا تعمل إعادة ضبط لقاعدة البيانات بسبب نسيان كلمة مرور.

### تجهيز اختصار الأوامر

من مجلد `fg-mtm-source/server` عرّف الدالة التالية في نفس جلسة SSH. تختار Caddy أو Compose الأساسي حسب وجود إعداد الدومين:

```bash
fgc() {
    if sudo grep -q '^FG_DOMAIN=' .env; then
        sudo docker compose -p fg-mtm -f compose.yml -f compose.https.yml "$@"
    else
        sudo docker compose -p fg-mtm -f compose.yml "$@"
    fi
}
fgc ps
```

لو اخترت يدويًا إعدادًا مختلفًا عن الدليل، عدّل ملفات Compose في الدالة لتطابق تثبيتك. الدالة تختفي عند إغلاق جلسة SSH؛ عرّفها مرة أخرى عند الحاجة.

### إنشاء حساب للمؤسسة والفرع

المؤسسة والفرع هنا نطاقان للبيانات، وليسا اسم مستخدم الراوتر. إنشاء حساب جديد يربطه بالمعرّفين؛ لا ينشئ بيانات عملاء أو يدمج فروعًا تلقائيًا.

لو التطبيق فيه بيانات، استعمل نفس المعرّفات الظاهرة في مزامنة الخادم. لتثبيت جديد يمكنك توليد معرّفين محليًا على السيرفر:

```bash
python3 - <<'PY'
import uuid
print("TENANT_ID=" + str(uuid.uuid4()))
print("BRANCH_ID=" + str(uuid.uuid4()))
PY
```

احتفظ بالقيم واستخدمها بدل `TENANT_ID` و`BRANCH_ID`. لا تولّد قيمًا جديدة لبيانات مؤسسة قائمة.

```bash
fgc run --rm api python -m fg_server account --tenant TENANT_ID --branch BRANCH_ID --username owner --role owner
```

سيطلب كلمة المرور مرتين دون إظهارها. حدها 12–128 حرفًا. اسم المستخدم يجب أن يكون فريدًا على هذا الخادم كله، حتى لو اختلف الفرع.

فرع إضافي في نفس المؤسسة، بحساب مختلف:

```bash
fgc run --rm api python -m fg_server account --tenant TENANT_ID --branch NEW_BRANCH_ID --username branch2-owner --role owner
```

حساب قراءة للوحة:

```bash
fgc run --rm api python -m fg_server account --tenant TENANT_ID --branch BRANCH_ID --username panel-reader --role reader
```

صلاحية reader ليست صلاحية مزامنة أعمال؛ المزامنة تحتاج owner. لا تغيّر نطاق حساب موجود عشوائيًا لنقل البيانات.

### معرفة الحسابات ومعرّفاتها وإعادة تعيين كلمة المرور

نزّل أداة الإدارة المرفقة بإصدار ثابت، وافحصها قبل التشغيل:

```bash
curl --fail --show-error --location https://raw.githubusercontent.com/FGMachines/FG-MTM/696587c1c3031d883336fac79f6ad7930236b641/scripts/server-admin.py --output server-admin.py
less server-admin.py
```

اخرج من less بالحرف q. الأداة تُشغّل داخل صورة API الموجودة؛ لا يحتاج السيرفر تثبيت psycopg خارج Docker:

```bash
fga() {
    fgc run --rm -e PYTHONPATH=/srv -v "$PWD/server-admin.py:/tmp/server-admin.py:ro" api python /tmp/server-admin.py "$@"
}
fga accounts
```

يعرض أسماء الحسابات ومعرّفات المؤسسة والفرع والصلاحية وحالة التفعيل، دون كلمات المرور أو بصماتها. لا تنشر قائمة حساباتك في جروب الدعم.

لو نسيت كلمة المرور:

```bash
fga reset-password --tenant TENANT_ID --branch BRANCH_ID --username owner
```

اكتب كلمة مرور جديدة مرتين. الأداة تتحقق من تطابق المؤسسة والفرع واسم الحساب، وتغيّر بصمة كلمة المرور وتزيل قفل محاولات الدخول وتلغي كل جلسات الحساب السابقة داخل معاملة واحدة. لا تغيّر الصلاحية ولا سجلات الأعمال، ولا تعيد تفعيل حساب معطّل. بعد النجاح سجل دخولك من جديد.

**لا يمكن إظهار كلمة المرور القديمة؛ هذه إعادة تعيين.** الأداة ليست صفحة «نسيت كلمة المرور» عامة، وتعمل فقط لمن يملك إدارة السيرفر. لا تحتاج إعادة بناء الصورة أو حذف قاعدة البيانات.

### نسخة احتياطية إضافية والتحقق منها

خذ نسخة قبل تحديث مهم. لا يتم نشر قاعدة البيانات للإنترنت:

```bash
umask 077
fg_backup_dir="$PWD/backups"
mkdir -p "$fg_backup_dir"
chmod 700 "$fg_backup_dir"
fg_stamp=$(date -u +%Y%m%d-%H%M%S)
fg_dump="$fg_backup_dir/fgmtm-$fg_stamp.dump"
if fgc exec -T db pg_dump -U fgmtm -Fc fgmtm > "$fg_dump.tmp"; then
    if test -s "$fg_dump.tmp"; then
        mv "$fg_dump.tmp" "$fg_dump"
        sha256sum "$fg_dump" > "$fg_dump.sha256"
        sudo install -m 600 .env "$fg_backup_dir/env-$fg_stamp"
        printf 'Backup: %s\n' "$fg_dump"
    else
        rm -f "$fg_dump.tmp"
        echo 'Backup is empty; do not continue with maintenance.' >&2
    fi
else
    rm -f "$fg_dump.tmp"
    echo 'Backup failed; do not continue with maintenance.' >&2
fi
```

انقل ملف dump وبصمته ونسخة env إلى مكان خاص خارج السيرفر. الملف env يحتوي أسرار الاتصال بقاعدة البيانات. النسخة لا تشمل ملفات شهادات Caddy أو إعدادات Nginx؛ احتفظ بها منفصلة وفق طريقة النشر.

للتحقق، ضع المسار الحقيقي لملف البصمة:

```bash
sha256sum -c /ABSOLUTE/PATH/fgmtm-TIMESTAMP.dump.sha256
```

البصمة تثبت سلامة الملف مقارنة بنسختك، لا تثبت أن الاستعادة نجحت.

### تجربة الاستعادة في قاعدة منفصلة

استخدم ملف النسخة الحقيقي. الاختبار التالي ينشئ قاعدة جديدة باسم `fgmtm_restore_check` ويترك قاعدة التشغيل `fgmtm` كما هي. لو قاعدة الاختبار موجودة بالفعل، لا تكرر الاستعادة فوقها؛ اختر اسم اختبار جديدًا وغيّره في كل الأوامر.

```bash
fgc exec -T db createdb -U fgmtm fgmtm_restore_check
fgc exec -T db pg_restore -U fgmtm -d fgmtm_restore_check --exit-on-error --single-transaction < /ABSOLUTE/PATH/fgmtm-TIMESTAMP.dump
fgc exec -T db psql -U fgmtm -d fgmtm_restore_check -c 'SELECT count(*) AS accounts FROM accounts;'
fgc exec -T db psql -U fgmtm -d fgmtm_restore_check -c 'SELECT count(*) AS revisions FROM business_sync_heads;'
```

توقف إذا فشل أي أمر؛ لا تعتبر ظهور عدد سجلات اختبارًا كاملًا للدخول أو المزامنة. قاعدة الاختبار تحتوي بيانات حقيقية أيضًا؛ احتفظ بها ضمن حماية السيرفر. استبدال قاعدة تشغيل قائمة يحتاج خطة صيانة ونسخة جديدة وإيقاف API وworker؛ لم نوفر أمرًا يمسح قاعدة التشغيل تلقائيًا.

### تشغيل الخدمات ومراجعة الأعطال

```bash
fgc ps
fgc logs --tail=100 api worker db
curl --fail --show-error http://127.0.0.1:8080/health
```

لو تغيّر منفذ loopback، غيّره في curl أيضًا. عند تعطل API أو worker، وبعد مراجعة السجلات:

```bash
fgc restart api worker
```

لا يعيد هذا إنشاء الحسابات ولا يحذف البيانات، لكنه يقطع الطلبات الجاري تنفيذها؛ راجع حالة آخر مزامنة قبل تكرارها.

عند إعادة تشغيل السيرفر أو توقف حاويات المشروع:

```bash
fgc up -d
```

لتشغيل قاعدة البيانات تلقائيًا بعد إعادة التشغيل:

```bash
fg_db_container=$(fgc ps -q db)
if test -n "$fg_db_container"; then
    sudo docker update --restart unless-stopped "$fg_db_container"
else
    echo 'Database container was not found; check fgc ps.' >&2
fi
```

راجع الدخول والتشخيص والمزامنة بعد رجوع الخدمات. لا تستخدم `down -v` أو حذف `.env` كحل لفشل تسجيل الدخول.

**التحقق من أداة الاستعادة:** نجحت 4 اختبارات منطقية تشمل تطابق النطاق، رفض الحساب المعطّل أو غير الموجود، رفض كلمة مرور قصيرة، وإلغاء إتمام المعاملة عند فشل إلغاء الجلسات. لم تُختبر الأداة على PostgreSQL أو VPS فعلي ضمن هذا التعديل.


## حل المشكلات

| المشكلة | تراجع إيه؟ |
| --- | --- |
| منافذ مستخدمة | اختار مسار Nginx أو منفذ loopback آخر؛ لا توقف مشروعات أخرى |
| فشل شهادة HTTPS | DNS وA/AAAA وإمكانية الوصول إلى 80 و443 |
| 502 من proxy | حالة API وسجلاته ورقم المنفذ المحلي |
| فشل إنشاء الحساب | المؤسسة والفرع، طول كلمة المرور، أو اسم حساب موجود |
| تسجيل الدخول يخرج من جهاز آخر | أنشئ حسابًا منفصلًا لكل جلسة متزامنة |
| بيانات التطبيق لا تظهر | المؤسسة والفرع وصلاحية owner ونتيجة المزامنة |
| Docker: permission denied | استخدم sudo كما في الدليل |
| طلب تسجيل الدخول يرجع 429 | انتظر قليلًا؛ تحديد معدل الطلبات يعمل |

**حدود التحقق:** تمت مراجعة الأوامر مقابل ملفات المصدر المحددة وفحص صياغة shell. لم يُنفّذ تثبيت جديد على VPS فعلي ضمن إعداد هذا الدليل، ولا يُدّعى نجاح DNS أو HTTPS أو MikroTik عندك قبل الاختبار.

[ملفات المصدر المحددة](https://github.com/nexvary/FG-MikroTik-Manager/tree/9f6e5e34f6e8754e43d282df4d225b942fbd2b94/server) · [شرح لوحة الخادم](USER-GUIDE-AR.md#server) · [العودة لصفحة المشروع](../README.md)
