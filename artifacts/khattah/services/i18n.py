"""Small, dependency-free localization catalog for the server-rendered UI."""

import re

CATALOG = {
    "en": {},
    "ar": {
        "Sign in": "تسجيل الدخول",
        "Create account": "إنشاء حساب",
        "Start your account": "ابدأ حسابك",
        "Explore demo": "استكشف العرض التجريبي",
        "A clearer way to participate": "طريقة أوضح للمشاركة",
        "Your package.": "باقتك.",
        "Clearly connected.": "متصلة بوضوح.",
        "Sign out": "تسجيل الخروج",
        "Overview": "نظرة عامة",
        "Home": "الرئيسية",
        "My Package": "باقاتي",
        "Package": "الباقة",
        "Invitations": "الدعوات",
        "Invite": "دعوة",
        "Transactions": "المعاملات",
        "History": "السجل",
        "Rewards": "المكافآت",
        "Profile": "الملف الشخصي",
        "Settings": "الإعدادات",
        "Admin": "الإدارة",
        "Member account": "حساب عضو",
        "Event-driven packages": "باقات قائمة على الأحداث",
        "Five paid, qualified participants complete a package.": "يكمل الباقة خمسة مشاركين مؤهلين ومدفوعي الرسوم.",
        "Your participation, visible": "مشاركتك، واضحة أمامك",
        "Welcome back": "مرحباً بعودتك",
        "Get started": "ابدأ الآن",
        "Sign in to KHATTAH": "سجّل الدخول إلى ختّة",
        "Create your account": "أنشئ حسابك",
        "Continue to your personal dashboard.": "تابع إلى لوحة التحكم الشخصية.",
        "Join your package and keep your progress in view.": "انضم إلى باقتك وتابع تقدمك بوضوح.",
        "Full name": "الاسم الكامل",
        "Email address": "البريد الإلكتروني",
        "Password": "كلمة المرور",
        "Show": "إظهار",
        "Hide": "إخفاء",
        "Minimum 8 characters": "8 أحرف على الأقل",
        "Mobile Number": "رقم الهاتف",
        "Country code": "رمز الدولة",
        "Phone number": "رقم الهاتف",
        "Select": "اختيار",
        "Send verification code": "إرسال رمز التحقق",
        "Verify mobile number": "تحقق من رقم الهاتف",
        "Verification Code": "رمز التحقق",
        "Enter your verification code": "أدخل رمز التحقق",
        "Verify": "تحقق",
        "Resend code": "إعادة إرسال الرمز",
        "Change number": "تغيير الرقم",
        "Development / testing mode": "وضع التطوير والاختبار",
        "Page not found": "الصفحة غير موجودة",
        "This page is outside the package.": "هذه الصفحة خارج الباقة.",
        "The page you requested does not exist.": "الصفحة التي طلبتها غير موجودة.",
        "Return home": "العودة إلى الرئيسية",
        "Dashboard": "لوحة التحكم",
        "Good morning": "صباح الخير",
        "Good afternoon": "مساء الخير",
        "Good evening": "مساء الخير",
        "Current package": "الباقة الحالية",
        "Qualified": "مؤهل",
        "Reward Available": "المكافأة متاحة",
        "Not yet available": "غير متاحة بعد",
        "Completed": "مكتمل",
        "Registered": "مسجل",
        "Package Created": "تم إنشاء الباقة",
        "Invited": "مدعو",
        "Paid / Activated": "مدفوع / مفعّل",
        "Available": "متاح",
        "No rewards yet.": "لا توجد مكافآت بعد.",
        "Save profile": "حفظ الملف الشخصي",
        "Save settings": "حفظ الإعدادات",
        "Preferences": "التفضيلات",
        "Notifications": "الإشعارات",
        "Email notifications": "إشعارات البريد الإلكتروني",
        "Invitation reminders": "تذكيرات الدعوات",
        "Language": "اللغة",
        "Preferred language": "اللغة المفضلة",
        "Choose your preferred interface language.": "اختر لغة الواجهة المفضلة لديك.",
        "English": "الإنجليزية",
        "Arabic": "العربية",
        "Users": "المستخدمون",
        "Packages": "الباقات",
        "Invitation catalogue": "دليل رسائل الدعوة",
        "Create and govern official messages in a dedicated workspace.": "أنشئ الرسائل الرسمية وأدرها في مساحة عمل مخصصة.",
        "Presentation": "العرض",
        "Appearance themes": "سمات المظهر",
        "Manage frontend and admin themes, palettes, and package labels.": "أدر سمات واجهة الأعضاء والإدارة ولوحات الألوان وتسميات الباقات.",
        "Open Appearance": "فتح إعدادات المظهر",
        "Rewards": "المكافآت",
        "Action": "الإجراء",
        "Status": "الحالة",
        "Participant": "المشارك",
        "Invited by": "دعا بواسطة",
        "Mark mock paid": "تسجيل الدفع التجريبي",
        "Recorded": "مسجل",
        "All packages": "كل الباقات",
        "Accounts": "الحسابات",
        "No change was needed.": "لم يكن هناك تغيير مطلوب.",
        "You have been signed out.": "تم تسجيل خروجك.",
        "Enter your name, a valid email, and a password with at least 8 characters.": "أدخل اسمك وبريداً إلكترونياً صالحاً وكلمة مرور من 8 أحرف على الأقل.",
        "Those sign-in details do not match our records.": "بيانات تسجيل الدخول هذه لا تطابق سجلاتنا.",
        "Add an email address or phone number to send an invitation.": "أضف بريداً إلكترونياً أو رقم هاتف لإرسال الدعوة.",
        "Invitation added to your list.": "أُضيفت الدعوة إلى قائمتك.",
        "Profile updated.": "تم تحديث الملف الشخصي.",
        "Settings saved.": "تم حفظ الإعدادات.",
        "Start registration before verifying a mobile number.": "ابدأ التسجيل قبل التحقق من رقم الهاتف.",
        "Mobile number verified. Your Khattah account is ready.": "تم التحقق من رقم الهاتف. حساب ختّة جاهز.",
        "This mobile number is already verified.": "رقم الهاتف هذا موثق بالفعل.",
        "Select a valid country calling code.": "اختر رمز اتصال دولياً صالحاً.",
        "Enter a valid mobile number.": "أدخل رقم هاتف صالحاً.",
        "Verification request not found.": "لم يُعثر على طلب التحقق.",
        "Verification code expired. Request a new code.": "انتهت صلاحية رمز التحقق. اطلب رمزاً جديداً.",
        "Verification attempts exhausted. Request a new code later.": "استُنفدت محاولات التحقق. اطلب رمزاً جديداً لاحقاً.",
        "Close": "إغلاق",
        "Move with confidence.": "تحرك بثقة.",
        "See every connection.": "شاهد كل اتصال.",
        "A simple home for your package, invitations, status, and account activity.": "مساحة بسيطة لباقتك ودعواتك وحالتك ونشاط حسابك.",
        "Verify your mobile": "تحقق من هاتفك",
        "A development mock SMS was sent to": "تم إرسال رسالة SMS تجريبية للتطوير إلى",
        "No paid SMS provider is connected. Codes are never displayed in this page, the API, logs, or admin tools.": "لا يوجد مزود SMS مدفوع متصل. لا تظهر الرموز في هذه الصفحة أو API أو السجلات أو أدوات الإدارة.",
        "6-digit code": "رمز من 6 أرقام",
        "Your full name": "اسمك الكامل",
        "name@example.com": "name@example.com",
        "Already have an account?": "لديك حساب بالفعل؟",
        "New to KHATTAH?": "جديد على ختّة؟",
        "Member preview": "معاينة العضو",
        "Open member dashboard": "فتح لوحة العضو",
        "Canada / United States": "كندا / الولايات المتحدة",
        "United Kingdom": "المملكة المتحدة",
        "Kenya": "كينيا",
        "Somalia": "الصومال",
        "Nigeria": "نيجيريا",
        "Ghana": "غانا",
        "Ethiopia": "إثيوبيا",
        "Uganda": "أوغندا",
        "Tanzania": "تنزانيا",
        "South Africa": "جنوب أفريقيا",
        "United Arab Emirates": "الإمارات العربية المتحدة",
        "Saudi Arabia": "المملكة العربية السعودية",
        "Qatar": "قطر",
        "Kuwait": "الكويت",
        "Australia": "أستراليا",
        "Active": "نشطة",
        "Administrator": "مسؤول",
        "Build your package with clarity": "ابنِ باقتك بوضوح",
        "KHATTAH dashboard": "لوحة تحكم ختّة",
        "KHATTAH is a clear, package-based financial participation platform.": "ختّة منصة واضحة للمشاركة المالية القائمة على الباقات.",
        "MY PACKAGE": "باقاتي",
        "Mobile Not Verified": "الهاتف غير موثق",
        "Mobile Verified": "الهاتف موثق",
        "Mobile number verified": "تم التحقق من رقم الهاتف",
        "Not verified. Mobile changes require a verification flow.": "غير موثق. تغيير الهاتف يتطلب مسار تحقق.",
        "Paid": "مدفوع",
        "Position": "الموضع",
        "Preview of a Khattah package": "معاينة باقة ختّة",
        "User": "المستخدم",
        "Verified mobile number": "رقم الهاتف الموثق",
        "Your account": "حسابك",
        "is complete": "مكتملة",
        "qualified": "مؤهل",
        "sent": "مُرسل",
        "total": "الإجمالي",
        "KHATTAH FOUNDATION": "مؤسسة ختّة",
        "authentication required": "المصادقة مطلوبة",
        "administrator access required": "يلزم الوصول بصلاحيات المسؤول",
        "invalid csrf token": "رمز حماية الطلب غير صالح",
        "recipient is required": "المستلم مطلوب",
        "completed package": "باقة مكتملة",
        "retained in history.": "محفوظة في السجل.",
        "Invitation sent to": "تم إرسال دعوة إلى",
        "marked paid / activated": "تم تسجيله مدفوعاً / مفعّلاً",
        "qualified in position": "تأهل في الموضع",
        "for Package": "للباقة",
        "Reward available for Package": "المكافأة متاحة للباقة",
        "Package created": "تم إنشاء الباقة",
        "Package completed": "اكتملت الباقة",
        "Activation": "التفعيل",
        "Package": "الباقة",
        "Primary navigation": "التنقل الرئيسي",
        "Mobile navigation": "التنقل على الهاتف",
        "Your account today": "حسابك اليوم",
        "Package progress updates whenever a paid participant qualifies.": "يتحدث تقدم الباقة عند تأهل مشارك مدفوع.",
        "Invite someone": "دعوة شخص",
        "The first five paid and qualified participants complete this package. Completion is event-driven, never monthly.": "يكمل هذه الباقة أول خمسة مشاركين مدفوعي الرسوم ومؤهلين. الإكمال قائم على الأحداث وليس شهرياً.",
        "The first five paid / activated participants fill the five qualifying positions in a package.": "يملأ أول خمسة مشاركين مدفوعين أو مفعّلين مواضع التأهل الخمسة في الباقة.",
        "Your next package is ready to begin": "باقتك التالية جاهزة للبدء",
        "of 5 qualified": "من 5 مؤهلين",
        "At a glance": "نظرة سريعة",
        "Live account status": "حالة الحساب الحالية",
        "Package progress": "تقدم الباقة",
        "View packages": "عرض الباقات",
        "Invited or registered people do not qualify until activated.": "لا يتأهل المدعوون أو المسجلون حتى يتم تفعيلهم.",
        "Manage invites": "إدارة الدعوات",
        "Mock payment status": "حالة الدفع التجريبي",
        "Activations are recorded by an administrator for testing.": "يسجل المسؤول عمليات التفعيل للاختبار.",
        "View history": "عرض السجل",
        "Reward status": "حالة المكافأة",
        "No money is sent automatically. Eligibility remains recorded.": "لا تُرسل الأموال تلقائياً. تبقى الأهلية مسجلة.",
        "View rewards": "عرض المكافآت",
        "Permanent timeline": "الخط الزمني الدائم",
        "Recent activity": "النشاط الأخير",
        "View all": "عرض الكل",
        "No activity yet": "لا يوجد نشاط بعد",
        "Your package events will appear here.": "ستظهر أحداث باقتك هنا.",
        "Status guide": "دليل الحالات",
        "Know what each color means": "اعرف معنى كل لون",
        "Registered / Invited": "مسجل / مدعو",
        "Paid / Activated / Qualified": "مدفوع / مفعّل / مؤهل",
        "Package Completed": "اكتملت الباقة",
        "Event-driven participation": "مشاركة قائمة على الأحداث",
        "My Packages": "باقاتي",
        "Each package has its own ID, five qualifying positions, and permanent history.": "لكل باقة معرّف خاص وخمسة مواضع تأهل وسجل دائم.",
        "Add invitation": "إضافة دعوة",
        "Qualified participants": "المشاركون المؤهلون",
        "Five qualifying positions": "خمسة مواضع للتأهل",
        "Open position": "موضع مفتوح",
        "Waiting for a paid participant": "بانتظار مشارك مدفوع",
        "Its reward eligibility has been recorded. You may begin another package without waiting for a new month.": "تم تسجيل أهلية المكافأة. يمكنك بدء باقة أخرى دون انتظار شهر جديد.",
        "Start next package": "بدء الباقة التالية",
        "Permanent record": "السجل الدائم",
        "Package history": "سجل الباقات",
        "Created": "أُنشئت",
        "Grow your package": "وسّع باقتك",
        "Invite as many people as you like. Only the first five paid and qualified participants fill a package.": "ادعُ العدد الذي تريده. أول خمسة مشاركين مدفوعي الرسوم ومؤهلين يملؤون الباقة.",
        "New invitation": "دعوة جديدة",
        "Bring someone into your package": "أدخل شخصاً إلى باقتك",
        "Inviting or registering does not qualify someone. An admin mock activation is required for testing.": "الدعوة أو التسجيل لا يؤهلان الشخص. يلزم تفعيل تجريبي من المسؤول للاختبار.",
        "Email or phone": "البريد الإلكتروني أو الهاتف",
        "Add invite": "إضافة الدعوة",
        "Invitation history": "سجل الدعوات",
        "People you invited": "الأشخاص الذين دعوتهم",
        "Recipient": "المستلم",
        "Sent": "أُرسلت",
        "Package position": "موضع الباقة",
        "Eligibility record": "سجل الأهلية",
        "A reward becomes available when its five-participant package completes. No money is sent automatically.": "تتوفر المكافأة عند اكتمال باقتها المكونة من خمسة مشاركين. لا تُرسل الأموال تلقائياً.",
        "Eligibility recorded": "سُجلت الأهلية",
        "Payment amount": "مبلغ الدفع",
        "Not configured": "غير مهيأ",
        "Payout status": "حالة الصرف",
        "Disabled": "معطل",
        "No reward available yet": "لا توجد مكافأة متاحة بعد",
        "Complete all five qualifying positions in a package to create a reward eligibility record.": "أكمل مواضع التأهل الخمسة في الباقة لإنشاء سجل أهلية المكافأة.",
        "View package progress": "عرض تقدم الباقة",
        "Keep your personal information current.": "حافظ على تحديث معلوماتك الشخصية.",
        "Email changes will be enabled with full account verification.": "سيتم تفعيل تغيير البريد بعد التحقق الكامل من الحساب.",
        "Member since": "عضو منذ",
        "Choose how KHATTAH communicates with you.": "اختر طريقة تواصل ختّة معك.",
        "Control your account messages and reminders.": "تحكم في رسائل الحساب والتذكيرات.",
        "Receive general account updates.": "استقبل تحديثات الحساب العامة.",
        "Receive updates about pending invitations.": "استقبل تحديثات الدعوات المعلقة.",
        "Authorized administration": "إدارة مصرح بها",
        "Khattah Admin": "إدارة ختّة",
        "Manage mock activations and inspect permanent package, reward, and participant records.": "أدر التفعيلات التجريبية وراجع سجلات الباقات والمكافآت والمشاركين الدائمة.",
        "Development controls": "أدوات التطوير",
        "Mock payment / activation queue": "قائمة الدفع / التفعيل التجريبي",
        "Mark mock paid": "تسجيل الدفع التجريبي",
        "Package ledger": "سجل الباقات",
        "Eligibility ledger": "سجل الأهلية",
        "Account record": "سجل الحساب",
        "A clear history of account activity. No payment processing is active.": "سجل واضح لنشاط الحساب. لا توجد معالجة دفع مفعلة.",
        "Foundation mode": "وضع الأساس",
        "Amounts and payment actions are intentionally disabled until you provide the exact Khattah rules.": "تم تعطيل المبالغ وإجراءات الدفع عمداً حتى تحدد قواعد ختّة الدقيقة.",
        "Recent records": "السجلات الأخيرة",
        "A clearer way to participate": "طريقة أوضح للمشاركة",
        "KHATTAH brings participation, invitations, and account progress into one simple place—designed to keep every step visible.": "تجمع ختّة المشاركة والدعوات وتقدم الحساب في مكان واحد بسيط، لتبقى كل خطوة واضحة.",
        "Event-driven packages. No monthly reward restriction.": "باقات قائمة على الأحداث. لا يوجد قيد شهري على المكافآت.",
        "Everything in one view": "كل شيء في عرض واحد",
        "Paid / Active": "مدفوع / نشط",
        "5 paid, qualified participants complete a package": "يكمل الباقة 5 مشاركين مدفوعين ومؤهلين",
        "One system. Four clear status signals.": "نظام واحد. أربع حالات واضحة.",
        "Eligible to receive": "مؤهل للاستلام",
        "Invitation Messages": "رسائل الدعوات",
        "Invitation unavailable": "الدعوة غير متاحة",
        "This invitation link is invalid or has expired.": "رابط الدعوة غير صالح أو منتهي.",
        "Bilingual sharing messages": "رسائل مشاركة ثنائية اللغة",
        "Open Invitation Messages": "فتح رسائل الدعوات",
        "Back to Admin": "العودة إلى الإدارة",
        "Manage every official bilingual sharing message, its approval state, and its audit history.": "إدارة كل رسالة مشاركة رسمية ثنائية اللغة وحالة اعتمادها وسجل تدقيقها.",
        "Create": "إنشاء",
        "New official message": "رسالة رسمية جديدة",
        "Campaign name": "اسم الحملة",
        "Subject": "الموضوع",
        "Use only {inviter_name} and {invite_link}": "استخدم {inviter_name} و{invite_link} فقط",
        "Create message": "إنشاء الرسالة",
        "Edit": "تعديل",
        "Edit message": "تعديل الرسالة",
        "Save changes": "حفظ التغييرات",
        "Approve": "اعتماد",
        "Activate": "تفعيل",
        "Deactivate": "إلغاء التفعيل",
        "Archive": "أرشفة",
        "Approved": "معتمد",
        "Active": "نشط",
        "Archived": "مؤرشف",
        "Created": "أُنشئ",
        "Updated": "حُدّث",
        "Yes": "نعم",
        "No": "لا",
        "Audit history": "سجل التدقيق",
        "No audit history": "لا يوجد سجل تدقيق",
        "Select an official message": "اختر رسالة رسمية",
        "Signed invite link": "رابط الدعوة الموقّع",
        "Copy Link": "نسخ الرابط",
        "WhatsApp": "واتساب",
        "SMS": "رسالة نصية",
        "Email": "البريد الإلكتروني",
        "Facebook": "فيسبوك",
        "Messenger": "ماسنجر",
        "Telegram": "تلغرام",
        "General Share": "مشاركة عامة",
        "Message is no longer available for sharing.": "الرسالة لم تعد متاحة للمشاركة.",
        "Messenger sharing is available from the Facebook share dialog.": "مشاركة ماسنجر متاحة من نافذة مشاركة فيسبوك.",
        "Official message preview": "معاينة الرسائل الرسمية",
        "Available sharing messages": "رسائل المشاركة المتاحة",
        "No approved messages are currently available.": "لا توجد رسائل معتمدة متاحة حالياً.",
        "Copy message for Messenger": "نسخ الرسالة لماسنجر",
        "Open Messenger": "فتح ماسنجر",
    },
}


def normalize_language(value):
    return value if value in CATALOG else "en"


def translate(value, language="en", **variables):
    language = normalize_language(language)
    # Historical audit rows may still contain Circle wording. Render those
    # rows with canonical Package terminology without mutating stored data.
    legacy_value = value.replace("Circle", "Package").replace("circle", "package")
    if legacy_value != value:
        return translate(legacy_value, language, **variables)
    if value == "qualified progress":
        return (
            f"{variables.get('count', 0)} / {variables.get('total', 5)} Qualified"
            if language == "en"
            else f"{variables.get('count', 0)} / {variables.get('total', 5)} مؤهل"
        )
    if value == "package heading":
        return (
            f"Package #{variables.get('number')}"
            if language == "en"
            else f"الباقة #{variables.get('number')}"
        )
    if value == "package complete":
        return (
            f"Package #{variables.get('number')} is complete"
            if language == "en"
            else f"الباقة #{variables.get('number')} مكتملة"
        )
    if value == "mock activations":
        count = variables.get("count", 0)
        return (
            f"{count} mock activation" + ("" if count == 1 else "s")
            if language == "en"
            else f"{count} " + ("تفعيل تجريبي" if count == 1 else "تفعيلات تجريبية")
        )
    if value == "completed packages retained in history":
        count = variables.get("count", 0)
        return (
            f"{count} completed package" + ("" if count == 1 else "s") + " retained in history."
            if language == "en"
            else f"{count} " + ("باقة مكتملة محفوظة" if count == 1 else "باقات مكتملة محفوظة") + " في السجل."
        )
    if value == "invitations sent":
        count = variables.get("count", 0)
        return (
            f"{count} invitation" + ("" if count == 1 else "s") + " sent"
            if language == "en"
            else f"{count} " + ("دعوة مُرسلة" if count == 1 else "دعوات مُرسلة")
        )
    if language == "ar":
        match = re.fullmatch(r"(\d+)\s*/\s*5\s+Qualified", value)
        if match:
            return f"{match.group(1)} / 5 مؤهل"
        match = re.fullmatch(r"(\d+)\s+mock activations?", value)
        if match:
            count = int(match.group(1))
            return f"{count} " + ("تفعيل تجريبي" if count == 1 else "تفعيلات تجريبية")
        match = re.fullmatch(r"(\d+)\s+completed packages?\s+retained in history\.", value)
        if match:
            count = int(match.group(1))
            return f"{count} " + ("باقة مكتملة محفوظة" if count == 1 else "باقات مكتملة محفوظة") + " في السجل."
        match = re.fullmatch(r"(\d+)\s+invitations?\s+sent", value)
        if match:
            count = int(match.group(1))
            return f"{count} " + ("دعوة مُرسلة" if count == 1 else "دعوات مُرسلة")
        match = re.fullmatch(r"Package #(\d+) is ready\.", value)
        if match:
            return f"الباقة #{match.group(1)} جاهزة."
        if value.startswith("Invitation sent to "):
            return "تم إرسال دعوة إلى " + value[len("Invitation sent to "):]
        if value.endswith(" marked paid / activated"):
            return value[:-len(" marked paid / activated")] + " " + CATALOG["ar"]["marked paid / activated"]
        if " qualified in position " in value and " for Package #" in value:
            name, rest = value.split(" qualified in position ", 1)
            position, package_number = rest.split(" for Package #", 1)
            return f"{name} تأهل في الموضع {position} للباقة #{package_number}"
        if value.startswith("Reward available for Package #"):
            return "المكافأة متاحة للباقة #" + value.split("#", 1)[1]
        if value.startswith("Package #") and value.endswith(" created"):
            return "تم إنشاء الباقة #" + value.split("#", 1)[1][:-len(" created")]
        if value.startswith("Package #") and value.endswith(" completed"):
            return "اكتملت الباقة #" + value.split("#", 1)[1][:-len(" completed")]
        match = re.fullmatch(r"Package #(\d+) is complete", value)
        if match:
            return f"الباقة #{match.group(1)} مكتملة"
        if value.startswith("Incorrect verification code."):
            remaining = value.split(". ", 1)[1].replace(
                " attempts remaining", " محاولات متبقية"
            )
            return "رمز التحقق غير صحيح. " + remaining + "."
        if value.startswith("Wait ") and value.endswith(" seconds before requesting another code."):
            seconds = value.split(" ", 2)[1]
            return f"انتظر {seconds} ثانية قبل طلب رمز آخر."
        if value.startswith("Too many verification"):
            return "تم طلب رموز تحقق كثيرة. حاول لاحقاً."
    return CATALOG[language].get(value, value)