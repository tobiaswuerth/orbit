"""Names, addresses and file names: the keys duplicate detection compares, and safe file names."""

import pytest

from orbit import config, names
from orbit.names import Nicknames


@pytest.mark.parametrize(
    "text, folded",
    [
        ("Hans Müller", "hans mueller"),
        ("MÜLLER", "mueller"),
        ("Straße", "strasse"),
        ("Jörg Böhi", "joerg boehi"),
        ("Zoë Bérard", "zoe berard"),
        ("Søren Ærø Łukasz", "soren aero lukasz"),
        ("Müller", "mueller"),  # decomposed ü
    ],
)
def test_fold(text, folded):
    assert names.fold(text) == folded


@pytest.mark.parametrize(
    "name", ["Hans Müller", "Müller Hans", "Müller, Hans", "hans mueller", "Dr. Hans Müller", "Prof. Dr. Müller Hans"]
)
def test_name_keys_ignore_order_case_umlauts_and_titles(name):
    assert names.parse_name(name).key == "hans mueller"


def test_name_parts():
    parts = names.parse_name("dipl. Ing. H. Müller")
    assert (parts.full, parts.initials, parts.surname) == (("mueller",), ("h",), "mueller")
    assert names.parse_name("Müller, Hans").surname == "mueller"
    assert names.parse_name("Hans Müller-Meier").full == ("hans", "muellermeier")
    assert names.parse_name("H Müller").initials == ("h",)
    assert names.parse_name("").key == ""
    assert names.parse_name("Dr.").surname is None


@pytest.mark.parametrize(
    "word, code",
    [
        ("Müller-Lüdenscheidt", "65752682"),
        ("Wikipedia", "3412"),
        ("Breschnew", "17863"),
        ("Müller", "657"),
        ("Mueller", "657"),
        ("Möller", "657"),
        ("Christoph", "47823"),
        ("Cäsar", "487"),
        ("Acht", "042"),
        ("Philipp", "351"),
        ("Dietz", "28"),
        ("Axel", "0485"),
        ("Lux", "548"),
        ("Hexe", "048"),
        ("Gross", "478"),
        ("Bachmann", "1466"),
        ("Schmid", "862"),
        ("Fux", "348"),
        ("", ""),
    ],
)
def test_koelner_phonetik(word, code):
    assert names.koelner(word) == code


@pytest.mark.parametrize(
    "name, key",
    [
        ("Acme AG", "acme"),
        ("ACME Aktiengesellschaft", "acme"),
        ("Müller & Söhne GmbH", "mueller soehne"),
        ("Café du Lac Sàrl", "cafe du lac"),
        ("Acme Holding SA", "acme holding"),
        ("AG", "ag"),  # nothing left but the legal form: keep it
    ],
)
def test_organization_keys_drop_the_legal_form(name, key):
    assert names.org_key(name) == key


def test_emails():
    assert names.email(" Hans.Mueller@Acme-AG.example ") == "hans.mueller@acme-ag.example"
    assert names.domain("hans@acme-ag.example") == "acme-ag.example"
    assert names.email_tokens("hansi.mueller+crm@gmail.com") == ["hansi", "mueller"]
    assert names.email_tokens("h_mueller-2@x.example") == ["h", "mueller"]
    for bad in ["", "no-at", "a@b", "a b@x.example", "a@@x.example", "a@x..example"]:
        assert not names.is_email(bad), bad
    assert names.is_email("anna.keller@acme-ag.example")


@pytest.mark.parametrize(
    "text, address",
    [
        (" Anna.Keller@Acme-AG.example ", "anna.keller@acme-ag.example"),
        ("Anna Keller <anna.keller@acme-ag.example>", "anna.keller@acme-ag.example"),
        ('"Keller, Anna" <Anna.Keller@acme-ag.example> ', "anna.keller@acme-ag.example"),
        ("<anna.keller@acme-ag.example>", "anna.keller@acme-ag.example"),
        ("Anna Keller", None),
        ("Anna <not an address>", None),
        ("a <b@x.example> <c@x.example>", None),
        (None, None),
    ],
)
def test_an_address_bare_or_as_a_header_writes_it(text, address):
    assert names.address(text) == address


def test_role_addresses():
    roles = {"info", "noreply"}
    assert names.is_role_address("info@acme.example", roles)
    assert names.is_role_address("Info+news@acme.example", roles)
    assert not names.is_role_address("hans@acme.example", roles)


@pytest.mark.parametrize("address", ["anna.office@acme.example", "max.sales@acme.example", "max.hr@acme.example"])
def test_a_person_s_address_with_a_role_word_in_it_stays_theirs(address):
    # A team's acme-support@ can't be told from a person's anna.office@ by its words: only a whole role is a mailbox.
    assert not names.is_role_address(address, set(config.ROLE_ADDRESSES))


def test_hr_and_service_mailboxes_are_roles_by_default():
    assert {"hr", "service"} <= set(config.ROLE_ADDRESSES)


def test_the_domains_a_domain_is_under():
    assert names.parent_domains("students.school.example") == ["school.example"]
    assert names.parent_domains("a.b.acme.example") == ["b.acme.example", "acme.example"]
    assert names.parent_domains("school.example") == names.parent_domains("localhost") == []


def test_domains():
    assert names.normalize_domain(" Acme-AG.example. ") == "acme-ag.example"
    assert names.normalize_domain("https://www.acme.example/about") == "acme.example"
    assert names.is_domain("acme-ag.example")
    for bad in ["", "acme", "-acme.example", "acme..example", "ac me.example"]:
        assert not names.is_domain(bad), bad


@pytest.mark.parametrize(
    "phone, key",
    [
        ("+41 52 123 45 67", "521234567"),
        ("052 123 45 67", "521234567"),
        ("0041521234567", "521234567"),
        ("12 34", None),
    ],
)
def test_phone_keys(phone, key):
    assert names.phone_key(phone) == key


@pytest.mark.parametrize(
    "name, safe",
    [
        ("Hans Müller", "Hans Müller"),
        ("2026-10-14 Email – AW: Offerte Wartungsvertrag 2027", "2026-10-14 Email – AW Offerte Wartungsvertrag 2027"),
        ('a/b\\c?d*e"f<g>h|i', "abcdefghi"),
        ("Links [[x]] #tag ^block", "Links x tag block"),
        ("  dots and spaces.  ", "dots and spaces"),
        ("tab\tand\nnewline", "tab and newline"),
        ("CON", "CON_"),
        ("lpt1", "lpt1_"),
        ("???", "Untitled"),
        ("x" * 200, "x" * 120),
        ("word " * 40, ("word " * 24).strip()),
    ],
)
def test_file_names_are_safe_on_windows_and_in_links(name, safe):
    assert names.file_name(name) == safe


def test_file_keys_compare_names_as_links_do():
    assert names.file_key("Hans Müller") == names.file_key("hans müller")


def test_nicknames():
    nicknames = Nicknames.parse("# comment\nHans = Hansi = Hansruedi\n\nJakob = Köbi\nbroken line\n")
    assert nicknames.variants("hansi") == {"hans", "hansi", "hansruedi"}
    assert nicknames.variants("koebi") == {"jakob", "koebi"}
    assert nicknames.variants("anna") == {"anna"}
    assert nicknames.same("Hansi", "Hans")
    assert not nicknames.same("Hansi", "Jakob")


@pytest.mark.parametrize(
    "name, safe", [("Con.Inc", "Con_.Inc"), ("nul.md", "nul_.md"), ("Contoso", "Contoso"), ("Aux", "Aux_")]
)
def test_names_windows_reserves_with_an_extension_too(name, safe):
    assert names.file_name(name) == safe


@pytest.mark.parametrize("name", ["日本語のメール " * 30, "🎉" * 100, "Grüße aus Zürich " * 10])
def test_long_file_names_fit_in_the_bytes_linux_and_macos_allow(name):
    safe = names.file_name(name)
    assert len(safe.encode()) <= names.MAX_FILE_BYTES
    assert len(f"{safe} (999).md".encode()) <= 255
    assert name.startswith(safe)


def test_addresses_and_domains_with_umlauts():
    assert names.is_email("hans@müller.ch")
    assert names.is_domain("bücher.ch")
    assert not names.is_domain("bü_cher.ch")


def test_a_web_address_with_a_login_or_a_port_is_its_domain():
    assert names.normalize_domain("https://user@www.Acme.example:8080/about") == "acme.example"
