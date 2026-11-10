"""Djinni category snapshot from user-supplied public markup (2026-11-10)."""

from dataclasses import dataclass

from job_bot.models import SearchInputError

MAX_CATEGORIES = 50


@dataclass(frozen=True, slots=True)
class Category:
    """An official category key, display label, group, and optional parent."""

    key: str
    label: str
    group: str
    parent: str | None = None


CATEGORY_GROUPS = (
    "Розробка",
    "QA",
    "Креатив і геймдев",
    "Дані та аналітика",
    "Менеджмент",
    "Лідерство",
    "Операції (Ops)",
    "Hardware та інженерія",
    "Маркетинг і продажі",
    "Рекрутинг",
    "Інше",
)

CATEGORIES = (
    Category("JavaScript", "JavaScript / Front-End", "Розробка", None),
    Category("Angular", "Angular", "Розробка", "JavaScript"),
    Category("Markup", "Markup", "Розробка", "JavaScript"),
    Category("React.js", "React.js", "Розробка", "JavaScript"),
    Category("Svelte", "Svelte", "Розробка", "JavaScript"),
    Category("Vue.js", "Vue.js", "Розробка", "JavaScript"),
    Category("Fullstack", "Fullstack", "Розробка", None),
    Category("Java", "Java", "Розробка", None),
    Category(".NET", "C# / .NET", "Розробка", None),
    Category("Dotnet Desktop", "Desktop Apps", "Розробка", ".NET"),
    Category("WinForms", "WinForms", "Розробка", "Dotnet Desktop"),
    Category("WPF", "WPF", "Розробка", "Dotnet Desktop"),
    Category("Dotnet Mobile", "Mobile Apps", "Розробка", ".NET"),
    Category("MAUI", "MAUI", "Розробка", "Dotnet Mobile"),
    Category("Xamarin", "Xamarin", "Розробка", "Dotnet Mobile"),
    Category(".NET Gamedev", ".NET Gamedev", "Розробка", ".NET"),
    Category("Dotnet Cloud", "Server & Cloud", "Розробка", ".NET"),
    Category("Dotnet Web", "Web Apps", "Розробка", ".NET"),
    Category("ASP.NET", "ASP.NET", "Розробка", "Dotnet Web"),
    Category("Blazor", "Blazor", "Розробка", "Dotnet Web"),
    Category("Python", "Python", "Розробка", None),
    Category("PHP", "PHP", "Розробка", None),
    Category("Drupal", "Drupal", "Розробка", "PHP"),
    Category("Laravel", "Laravel", "Розробка", "PHP"),
    Category("Magento", "Magento", "Розробка", "PHP"),
    Category("Symfony", "Symfony", "Розробка", "PHP"),
    Category("WordPress", "WordPress", "Розробка", "PHP"),
    Category("Yii", "Yii", "Розробка", "PHP"),
    Category("Node.js", "Node.js", "Розробка", None),
    Category("iOS", "iOS", "Розробка", None),
    Category("Android", "Android", "Розробка", None),
    Category("React Native", "React Native", "Розробка", None),
    Category("C++", "C / C++ / Embedded", "Розробка", None),
    Category("C Lang", "C", "Розробка", "C++"),
    Category("CPP", "C++", "Розробка", "C++"),
    Category("Embedded", "Embedded", "Розробка", "C++"),
    Category("Flutter", "Flutter", "Розробка", None),
    Category("Golang", "Golang", "Розробка", None),
    Category("Ruby", "Ruby", "Розробка", None),
    Category("Scala", "Scala", "Розробка", None),
    Category("Salesforce", "Salesforce", "Розробка", None),
    Category("Rust", "Rust", "Розробка", None),
    Category("Elixir", "Elixir", "Розробка", None),
    Category("Kotlin", "Kotlin", "Розробка", None),
    Category("ERP", "ERP Systems", "Розробка", None),
    Category("MS Dynamics", "MS Dynamics / Business Central", "Розробка", "ERP"),
    Category("Odoo", "Odoo", "Розробка", "ERP"),
    Category("SAP", "SAP", "Розробка", "ERP"),
    Category("No Code", "No Code", "Розробка", None),
    Category("QA Hardware / Embedded", "QA Hardware / Embedded", "QA", None),
    Category("QA", "QA Manual", "QA", None),
    Category("QA Automation", "QA Automation", "QA", None),
    Category("Design", "Design", "Креатив і геймдев", None),
    Category(
        "Content Design", "Content Design / UX writer", "Креатив і геймдев", "Design"
    ),
    Category("Graphic Design", "Graphic Design", "Креатив і геймдев", "Design"),
    Category("Product Design", "Product Design", "Креатив і геймдев", "Design"),
    Category("UI UX", "UI/UX", "Креатив і геймдев", "Design"),
    Category("UX Research", "UX Research", "Креатив і геймдев", "Design"),
    Category("Artist", "2D/3D Artist / Illustrator", "Креатив і геймдев", None),
    Category("2D Animation", "2D Animation", "Креатив і геймдев", "Artist"),
    Category("2D Artist", "2D Artist", "Креатив і геймдев", "Artist"),
    Category("3D Animation", "3D Animation", "Креатив і геймдев", "Artist"),
    Category("3D Artist", "3D Artist", "Креатив і геймдев", "Artist"),
    Category("Illustrator", "Illustrator", "Креатив і геймдев", "Artist"),
    Category("Motion Design", "Motion Design", "Креатив і геймдев", "Artist"),
    Category("VFX Artist", "VFX Artist", "Креатив і геймдев", "Artist"),
    Category("Video Editor", "Video Editor", "Креатив і геймдев", "Artist"),
    Category("Unity", "Gamedev", "Креатив і геймдев", None),
    Category("Game Design", "Game Design", "Креатив і геймдев", "Unity"),
    Category("Game Developer", "Game Developer", "Креатив і геймдев", "Unity"),
    Category(
        "Unity Developer", "Unity Developer", "Креатив і геймдев", "Game Developer"
    ),
    Category(
        "Unreal Developer", "Unreal Developer", "Креатив і геймдев", "Game Developer"
    ),
    Category("Level Design", "Level Design", "Креатив і геймдев", "Unity"),
    Category("Business Analyst", "Business Analyst", "Дані та аналітика", None),
    Category("Data Science", "Data Science", "Дані та аналітика", None),
    Category("ML AI", "ML / AI", "Дані та аналітика", "Data Science"),
    Category("Data Analyst", "Data Analyst", "Дані та аналітика", None),
    Category("Web Analyst", "Web Analyst", "Дані та аналітика", None),
    Category("Data Engineer", "Data Engineer", "Дані та аналітика", None),
    Category("SQL", "SQL / DBA", "Дані та аналітика", None),
    Category("Project Manager", "Project Manager", "Менеджмент", None),
    Category("Product Manager", "Product Manager", "Менеджмент", None),
    Category("Product Owner", "Product Owner", "Менеджмент", None),
    Category("Delivery Manager", "Delivery Manager", "Менеджмент", None),
    Category("Scrum Master", "Scrum Master / Agile Coach", "Менеджмент", None),
    Category("Lead", "Tech Leadership", "Лідерство", None),
    Category("CTO", "CTO", "Лідерство", "Lead"),
    Category("Engineering Manager", "Engineering Manager", "Лідерство", "Lead"),
    Category("Architect", "Software Architect", "Лідерство", "Lead"),
    Category("Head Chief", "Head / Chief", "Лідерство", None),
    Category(
        "CBDO", "Chief Business Development Officer (CBDO)", "Лідерство", "Head Chief"
    ),
    Category("CCO", "Chief Commercial Officer (CCO)", "Лідерство", "Head Chief"),
    Category("CEO", "Chief Executive Officer (CEO)", "Лідерство", "Head Chief"),
    Category("CFO", "Chief Financial Officer (CFO)", "Лідерство", "Head Chief"),
    Category("CIO", "Chief Information Officer (CIO)", "Лідерство", "Head Chief"),
    Category("CMO", "Chief Marketing Officer (CMO)", "Лідерство", "Head Chief"),
    Category("COO", "Chief Operating Officer (COO)", "Лідерство", "Head Chief"),
    Category("CPO", "Chief Product Officer (CPO)", "Лідерство", "Head Chief"),
    Category("CSO", "Chief Security Officer (CSO)", "Лідерство", "Head Chief"),
    Category("DevOps", "DevOps", "Операції (Ops)", None),
    Category("Security", "Security", "Операції (Ops)", None),
    Category(
        "Information Security", "Information Security", "Операції (Ops)", "Security"
    ),
    Category("Penetration Tester", "Penetration Tester", "Операції (Ops)", "Security"),
    Category("Security Analyst", "Security Analyst", "Операції (Ops)", "Security"),
    Category("Sysadmin", "Sysadmin", "Операції (Ops)", None),
    Category("DefTech", "DefTech", "Hardware та інженерія", None),
    Category("Avionics", "Avionics", "Hardware та інженерія", "DefTech"),
    Category(
        "Electronic Warfare", "Electronic Warfare", "Hardware та інженерія", "DefTech"
    ),
    Category(
        "Military Software / C4ISR",
        "Military Software / C4ISR",
        "Hardware та інженерія",
        "DefTech",
    ),
    Category(
        "UAV / Drone Engineer",
        "UAV / Drone Engineer",
        "Hardware та інженерія",
        "DefTech",
    ),
    Category(
        "UAV / Drone Pilot", "UAV / Drone Pilot", "Hardware та інженерія", "DefTech"
    ),
    Category("Weapons Systems", "Weapons Systems", "Hardware та інженерія", "DefTech"),
    Category("Hardware", "Hardware", "Hardware та інженерія", None),
    Category(
        "ASIC / Chip Design", "ASIC / Chip Design", "Hardware та інженерія", "Hardware"
    ),
    Category(
        "Firmware Engineer", "Firmware Engineer", "Hardware та інженерія", "Hardware"
    ),
    Category("FPGA Engineer", "FPGA Engineer", "Hardware та інженерія", "Hardware"),
    Category(
        "Hardware Engineer", "Hardware Engineer", "Hardware та інженерія", "Hardware"
    ),
    Category("RF Engineer", "RF Engineer", "Hardware та інженерія", "Hardware"),
    Category(
        "Robotics Engineer", "Robotics Engineer", "Hardware та інженерія", "Hardware"
    ),
    Category(
        "Engineering / CAD Design",
        "Engineering / CAD Design",
        "Hardware та інженерія",
        None,
    ),
    Category(
        "CAD Designer",
        "CAD Designer",
        "Hardware та інженерія",
        "Engineering / CAD Design",
    ),
    Category(
        "Electrical Engineering",
        "Electrical Engineering",
        "Hardware та інженерія",
        "Engineering / CAD Design",
    ),
    Category(
        "Electronics / PCB Design",
        "Electronics / PCB Design",
        "Hardware та інженерія",
        "Engineering / CAD Design",
    ),
    Category(
        "Industrial Design",
        "Industrial Design",
        "Hardware та інженерія",
        "Engineering / CAD Design",
    ),
    Category(
        "Mechanical Engineering",
        "Mechanical Engineering",
        "Hardware та інженерія",
        "Engineering / CAD Design",
    ),
    Category("Marketing", "Marketing", "Маркетинг і продажі", None),
    Category("Advertising", "Advertising", "Маркетинг і продажі", "Marketing"),
    Category(
        "Affiliate Manager", "Affiliate Manager", "Маркетинг і продажі", "Advertising"
    ),
    Category("Media Buying", "Media Buying", "Маркетинг і продажі", "Advertising"),
    Category("PPC", "PPC", "Маркетинг і продажі", "Advertising"),
    Category(
        "Content Marketing", "Content Marketing", "Маркетинг і продажі", "Marketing"
    ),
    Category(
        "Content Manager", "Content Manager", "Маркетинг і продажі", "Content Marketing"
    ),
    Category(
        "Content Writing",
        "Content Writer / Copywriter / Editor",
        "Маркетинг і продажі",
        "Content Marketing",
    ),
    Category(
        "Digital Marketing", "Digital Marketing", "Маркетинг і продажі", "Marketing"
    ),
    Category(
        "Digital Marketing Manager",
        "Digital Marketing Manager",
        "Маркетинг і продажі",
        "Digital Marketing",
    ),
    Category(
        "Social Media", "Social Media", "Маркетинг і продажі", "Digital Marketing"
    ),
    Category(
        "Marketing Analyst", "Marketing Analyst", "Маркетинг і продажі", "Marketing"
    ),
    Category(
        "Performance Marketing",
        "Performance Marketing",
        "Маркетинг і продажі",
        "Marketing",
    ),
    Category("PR Manager", "PR Manager", "Маркетинг і продажі", "Marketing"),
    Category("Sales", "Sales", "Маркетинг і продажі", None),
    Category("Account Manager", "Account Manager", "Маркетинг і продажі", "Sales"),
    Category(
        "Business Development", "Business Development", "Маркетинг і продажі", "Sales"
    ),
    Category("Sales Leadership", "Sales Leadership", "Маркетинг і продажі", "Sales"),
    Category("Sales Manager", "Sales Manager", "Маркетинг і продажі", "Sales"),
    Category("Lead Generation", "Lead Generation", "Маркетинг і продажі", None),
    Category("SEO", "SEO", "Маркетинг і продажі", None),
    Category("HR", "HR", "Рекрутинг", None),
    Category("Recruiter", "Recruiter", "Рекрутинг", None),
    Category("Interviewer", "Interviewer", "Рекрутинг", None),
    Category("Technical Writing", "Technical Writing", "Інше", None),
    Category("Support", "Customer/Technical Support", "Інше", None),
    Category("Finances", "Finances", "Інше", None),
    Category("Accountant", "Accountant", "Інше", "Finances"),
    Category("Finance Manager", "Finance Manager", "Інше", "Finances"),
    Category("Financial Analyst", "Financial Analyst", "Інше", "Finances"),
    Category("FinOps", "FinOps", "Інше", "Finances"),
    Category("Other", "(Other)", "Інше", None),
)


def normalize_categories(values: tuple[str, ...]) -> tuple[str, ...]:
    """Validate official keys and canonicalize an unordered category selection."""
    selected = set(values)
    if len(selected) > MAX_CATEGORIES:
        raise SearchInputError("Choose at most 50 categories.")
    if not selected.issubset(category.key for category in CATEGORIES):
        raise SearchInputError("Please choose categories using the category picker.")
    return tuple(sorted(selected))
