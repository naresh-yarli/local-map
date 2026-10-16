from string import Template

TEMPLATE = Template("Customer $name total is $amount")


def render(name: str, amount: float) -> str:
    return TEMPLATE.substitute(name=name, amount=f"{amount:,.2f}")
