# Payment errors and charged-without-access
## Payment page errors
If the payment page shows an error, the customer should not retry more than twice. Errors such as 500 or "payment declined" are logged automatically.

## Charged but feature not unlocked
If a payment went through but the purchase is not visible, first ask the customer to restore purchases. If it is still missing, the agent grants the purchase manually in the admin panel using the transaction ID.
