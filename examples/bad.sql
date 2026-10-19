-- Copied from an Azure SQL project. Looks fine. Isn't.
CREATE TABLE dbo.orders (
    order_id    INT IDENTITY(1,1),
    customer_id VARCHAR(10) NOT NULL,
    created_at  DATETIME2 NOT NULL,
    status      VARCHAR(20) DEFAULT 'new',
    notes       VARCHAR(MAX),
    CONSTRAINT pk_orders PRIMARY KEY (order_id)
);
CREATE VIEW dbo.v_open_orders AS SELECT * FROM dbo.orders WHERE status = 'new';
GO
ALTER TABLE dbo.orders DROP COLUMN notes;
