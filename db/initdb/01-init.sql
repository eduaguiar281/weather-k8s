-- ============================================================
-- weather-db — Schema e dados iniciais
-- ============================================================

CREATE TABLE IF NOT EXISTS weather (
    id      SERIAL PRIMARY KEY,
    city    VARCHAR(50)  NOT NULL,
    date    DATE         NOT NULL,
    weather VARCHAR(100) NOT NULL
);

-- ============================================================
-- Seed: 5 cidades × 10 dias
-- ============================================================
INSERT INTO weather (city, date, weather) VALUES

-- São Paulo
('São Paulo', '2024-04-01', 'Cloudy with light drizzle'),
('São Paulo', '2024-04-02', 'Heavy rain throughout the day'),
('São Paulo', '2024-04-03', 'Partly cloudy'),
('São Paulo', '2024-04-04', 'Thunderstorms in the afternoon'),
('São Paulo', '2024-04-05', 'Overcast skies'),
('São Paulo', '2024-04-06', 'Sunny with mild breeze'),
('São Paulo', '2024-04-07', 'Light rain in the morning'),
('São Paulo', '2024-04-08', 'Cloudy'),
('São Paulo', '2024-04-09', 'Clear and sunny'),
('São Paulo', '2024-04-10', 'Foggy in the morning, clearing later'),

-- Rio de Janeiro
('Rio de Janeiro', '2024-04-01', 'Sunny and hot'),
('Rio de Janeiro', '2024-04-02', 'Partly cloudy, warm'),
('Rio de Janeiro', '2024-04-03', 'Clear skies, very hot'),
('Rio de Janeiro', '2024-04-04', 'Sunny with high humidity'),
('Rio de Janeiro', '2024-04-05', 'Scattered showers'),
('Rio de Janeiro', '2024-04-06', 'Sunny and breezy'),
('Rio de Janeiro', '2024-04-07', 'Partly cloudy'),
('Rio de Janeiro', '2024-04-08', 'Hot and humid'),
('Rio de Janeiro', '2024-04-09', 'Clear skies'),
('Rio de Janeiro', '2024-04-10', 'Light clouds, warm'),

-- Curitiba
('Curitiba', '2024-04-01', 'Cold and foggy'),
('Curitiba', '2024-04-02', 'Partly cloudy, chilly'),
('Curitiba', '2024-04-03', 'Light rain, cold'),
('Curitiba', '2024-04-04', 'Overcast and windy'),
('Curitiba', '2024-04-05', 'Foggy morning, cloudy afternoon'),
('Curitiba', '2024-04-06', 'Sunny but cold'),
('Curitiba', '2024-04-07', 'Heavy rain and strong winds'),
('Curitiba', '2024-04-08', 'Partly cloudy, cool'),
('Curitiba', '2024-04-09', 'Clear and cold'),
('Curitiba', '2024-04-10', 'Light frost, sunny'),

-- Manaus
('Manaus', '2024-04-01', 'Hot and humid, afternoon showers'),
('Manaus', '2024-04-02', 'Tropical thunderstorm'),
('Manaus', '2024-04-03', 'Very hot and muggy'),
('Manaus', '2024-04-04', 'Heavy tropical rain'),
('Manaus', '2024-04-05', 'Hot with scattered storms'),
('Manaus', '2024-04-06', 'Sunny and extremely hot'),
('Manaus', '2024-04-07', 'Humid with light showers'),
('Manaus', '2024-04-08', 'Overcast and hot'),
('Manaus', '2024-04-09', 'Tropical rain in the evening'),
('Manaus', '2024-04-10', 'Hot and sunny'),

-- Fortaleza
('Fortaleza', '2024-04-01', 'Sunny and windy'),
('Fortaleza', '2024-04-02', 'Clear skies, hot'),
('Fortaleza', '2024-04-03', 'Sunny with sea breeze'),
('Fortaleza', '2024-04-04', 'Partly cloudy, warm'),
('Fortaleza', '2024-04-05', 'Hot and sunny'),
('Fortaleza', '2024-04-06', 'Clear with strong winds'),
('Fortaleza', '2024-04-07', 'Sunny, very hot'),
('Fortaleza', '2024-04-08', 'Light clouds, warm breeze'),
('Fortaleza', '2024-04-09', 'Sunny and dry'),
('Fortaleza', '2024-04-10', 'Hot with isolated showers');
