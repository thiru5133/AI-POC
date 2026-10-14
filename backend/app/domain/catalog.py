"""Master data: the business domains a partner can belong to. Seeded by migration 0009 and by `seed()`.

Every business partner belongs to exactly one domain; there is deliberately no catch-all "generic" domain.
The persona and booking workflow here are what turn the shared engine into e.g. a hotel or a hospital receptionist.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class DomainDef:
    key: str
    name: str  # plural, shown in dropdowns: "Hotels"
    description: str
    persona: str  # "hotel receptionist"
    booking_resource: str
    booking_fields: tuple[str, ...]


DOMAINS: tuple[DomainDef, ...] = (
    DomainDef("hotel", "Hotels", "Hotels, resorts and guest houses", "hotel receptionist", "room",
              ("check_in", "check_out", "guests", "guest_name")),
    DomainDef("school", "Schools", "Schools, colleges and coaching centres", "school front-office assistant",
              "admission_visit", ("student_name", "grade", "parent_name", "phone")),
    DomainDef("hospital", "Hospitals", "Hospitals and clinics", "hospital reception and appointments desk",
              "appointment", ("department", "date", "patient_name", "phone")),
    DomainDef("restaurant", "Restaurants", "Restaurants, cafes and catering", "restaurant host",
              "table", ("date", "time", "party_size", "guest_name")),
    DomainDef("real_estate", "Real estate", "Property sales, rentals and site visits", "property consultant",
              "site_visit", ("property", "date", "visitor_name", "phone")),
    DomainDef("salon", "Salons & spas", "Salons, spas and wellness studios", "salon receptionist",
              "appointment", ("service", "date", "time", "guest_name")),
    DomainDef("fitness", "Fitness & gyms", "Gyms, studios and sports clubs", "fitness club front-desk assistant",
              "session", ("program", "date", "member_name", "phone")),
    DomainDef("automobile", "Automobile services", "Dealerships, service centres and garages", "service advisor",
              "service_slot", ("vehicle", "service", "date", "owner_name")),
)

BY_KEY = {d.key: d for d in DOMAINS}


def profile_config(domain: DomainDef, business_name: str) -> dict:
    """A new partner's starting profile: identity and booking workflow from its domain, no built-in facts."""
    return {
        "identity": {
            "organizationName": business_name,
            "persona": domain.persona,
            "greeting": f"Welcome to {business_name}. How can I help you?",
        },
        "bookingWorkflow": {"resourceType": domain.booking_resource, "requiredFields": list(domain.booking_fields)},
    }


def marketplace_profile_config(domain: DomainDef, name: str) -> dict:
    """The shared assistant that compares every partner of a domain."""
    return {
        "identity": {
            "organizationName": name,
            "persona": f"{domain.persona} serving all partner {domain.name.lower()}",
            "greeting": f"Hello! I can compare {domain.name.lower()} for you. What are you looking for?",
        },
        "knowledgeBase": {
            "info": {
                "How you help": (
                    f"You help callers compare and choose between the partner {domain.name.lower()} on this platform. "
                    "Look things up with the tools: they ask every partner at once and tell you which partner each "
                    "result is from. Summarise the best few options briefly. To book or cancel, confirm the details "
                    "and make that call for the one partner the caller picked, naming it."
                )
            }
        },
        "bookingWorkflow": {"resourceType": domain.booking_resource, "requiredFields": list(domain.booking_fields)},
    }
