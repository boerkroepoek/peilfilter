# Peilfilter

Streamlit-app die CSV-bestanden met grondwatermetingen analyseert en PDF-rapporten met GHG- en GLG-proxywaarden maakt.

## Periodes uitsluiten

Vóór het starten van de analyse kun je in **Periodes buiten beschouwing laten** één of meer periodes toevoegen. Voer begin- en einddatum handmatig in, of sleep over een tijdvak in de meetgrafiek en voeg de selectie toe. De begin- en einddatum tellen beide mee.

Metingen in uitgesloten periodes blijven zichtbaar in de grafiek en de gevalideerde data, maar worden niet gebruikt voor uitschieterdetectie of de GHG/GLG-berekening. De rapportgrafiek arceert deze periodes en het PDF-rapport vermeldt de uitgesloten periodes en het aantal metingen.
