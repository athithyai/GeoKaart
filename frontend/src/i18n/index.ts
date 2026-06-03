/** GeoKaart UI translations — EN and NL. No external library needed. */

export type Lang = 'en' | 'nl'

export const translations = {
  en: {
    // Header
    subtitle: 'Dutch Geospatial Intelligence',
    dataSources: 'CBS StatLine × PDOK',
    refreshIdle: 'Refresh spatial data',
    refreshRunning: 'Refreshing…',
    refreshLastUpdated: 'updated {date}',
    refreshData: 'refresh data',

    // Input bar
    inputPlaceholder: 'Ask about any place in the Netherlands…',
    inputHint: 'Enter to send · Shift+Enter for new line',

    // Chat bubbles
    retry: '↺ Try again',
    relatedData: 'Related data',

    // Plan card
    executionPlan: 'Execution plan',
    copy: 'Copy',

    // Map controls
    geoLayer: 'Geography layer',
    municipalities: 'municipalities',
    districts: 'districts',
    neighbourhoods: 'neighbourhoods',
    selected: 'Selected',
    deselectRegion: 'Deselect region',

    // Map legend
    noData: 'No data',
    regions: 'regions',

    // Data table
    dataTable: 'Data table',
    noDataSuffix: 'no data',
    regionCol: 'Region',
    valueCol: 'Value',

    // Greeting fast-path replies
    greetingReplies: [
      'Hello! Ask me about Dutch regional statistics. Try: "Population density per municipality" or "House values in Amsterdam."',
      'Hi! I make interactive maps from Dutch open data. What would you like to explore?',
      'Hey! Ask me anything about places in the Netherlands — statistics, housing, income, and more.',
    ],
    casualReplies: [
      'Ha! Ask me something about the Netherlands — e.g. "Gas consumption per municipality" or "Population density in Amsterdam".',
      "😄 Ready when you are. Try: \"House values per municipality in Utrecht\".",
      '😄 Come on — ask me something about Dutch regional data!',
    ],

    // Region selection suggestions
    regionSuggestions: (name: string) => [
      `What is the population density in ${name}?`,
      `House values in ${name}`,
      `Average income per resident in ${name}`,
      `Compare ${name} with surrounding municipalities`,
    ],
  },

  nl: {
    // Header
    subtitle: 'Nederlandse Geo-Intelligentie',
    dataSources: 'CBS StatLine × PDOK',
    refreshIdle: 'Ruimtelijke data vernieuwen',
    refreshRunning: 'Vernieuwen…',
    refreshLastUpdated: 'bijgewerkt {date}',
    refreshData: 'data vernieuwen',

    // Input bar
    inputPlaceholder: 'Stel een vraag over een plek in Nederland…',
    inputHint: 'Enter om te verzenden · Shift+Enter voor nieuwe regel',

    // Chat bubbles
    retry: '↺ Opnieuw proberen',
    relatedData: 'Gerelateerde data',

    // Plan card
    executionPlan: 'Uitvoeringsplan',
    copy: 'Kopiëren',

    // Map controls
    geoLayer: 'Geografisch niveau',
    municipalities: 'gemeenten',
    districts: 'wijken',
    neighbourhoods: 'buurten',
    selected: 'Geselecteerd',
    deselectRegion: 'Deselecteer regio',

    // Map legend
    noData: 'Geen data',
    regions: "regio's",

    // Data table
    dataTable: 'Datatabel',
    noDataSuffix: 'geen data',
    regionCol: 'Regio',
    valueCol: 'Waarde',

    // Greeting fast-path replies
    greetingReplies: [
      'Hallo! Vraag me iets over Nederlandse regionale statistieken. Probeer: "Bevolkingsdichtheid per gemeente" of "WOZ-waarde in Amsterdam".',
      'Hey! Ik maak interactieve kaarten van CBS-kerncijfers per gemeente. Wat wil je weten?',
      'Hoi! Stel een vraag over plaatsen in Nederland — statistieken, wonen, inkomen en meer.',
    ],
    casualReplies: [
      'Ha! Vraag me iets over Nederlandse statistieken — bijv. "Gasverbruik per gemeente" of "Bevolkingsdichtheid in Amsterdam".',
      'Haha 😄 Kom maar op met een vraag over CBS-data. Probeer: "WOZ-waarde per gemeente in Utrecht".',
      '😄 Ik ben er klaar voor. Stel een vraag over Nederlandse regionale cijfers!',
    ],

    // Region selection suggestions
    regionSuggestions: (name: string) => [
      `Wat is de bevolkingsdichtheid in ${name}?`,
      `WOZ-waarde in ${name}`,
      `Inkomen per inwoner in ${name}`,
      `Vergelijk ${name} met omliggende gemeenten`,
    ],
  },
} as const satisfies Record<Lang, unknown>

export type Translations = typeof translations.en
