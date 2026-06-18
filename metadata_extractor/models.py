from pydantic import BaseModel, Field
from typing import List

class PartyDetails(BaseModel):
    appellants_petitioners: List[str] = Field(
        description="Full names, descriptions, or titles of the Appellants, Petitioners, or Plaintiffs (e.g. ['John Doe (Appellant)', 'State (Petitioner)'])"
    )
    respondents: List[str] = Field(
        description="Full names, descriptions, or titles of the Respondents or Defendants (e.g. ['Jane Smith (Respondent)', 'Police Chief (Defendant)'])"
    )

class JudgmentMetadata(BaseModel):
    case_number: str = Field(
        description="The lead court reference, copied verbatim from the judgment's cover page (e.g. an 'SC Appeal No.', 'SC FR', or 'CA' style reference). Never output an example or placeholder value — extract the actual number from the text."
    )
    judges: List[str] = Field(
        description="Names of the Honorable Justice(s) who delivered or sat on the judgment panel."
    )
    authoring_judge: str = Field(
        description="The SINGLE Justice who wrote/delivered this judgment (its author) — their name appears at the very start of the opinion, before counsel and submissions are listed, often followed by 'delivered the judgment of the Court'. Output only that one name (e.g. 'Arjuna Obeyesekere, J.'). If genuinely unclear, use the first judge listed."
    )
    date_of_judgment: str = Field(
        description="The exact date the judgment was delivered. Output format must be YYYY-MM-DD if parseable, otherwise raw text from the document (e.g., '2026-06-08', '08th June 2026')."
    )
    parties: PartyDetails = Field(
        description="Structured division of opposing parties into appellants/petitioners and respondents."
    )
    legislation_cited: List[str] = Field(
        description="Explicit statutes, acts, constitutional articles, ordinances, or sections mentioned in the text (e.g., 'Section 68 of the Evidence Ordinance', 'Article 126 of the Constitution')."
    )
    keywords: List[str] = Field(
        description="5 to 10 highly relevant, standardized legal keywords or topics derived from the text context for index search (e.g., 'Writ of Certiorari', 'Prescriptive Title', 'Wrongful Dismissal')."
    )
