UCD_OWNER = "UCD-Owner"
UCD_FULL_ADMIN = "UCD-Full-Admin"
UCD_BILLING = "UCD-Billing-Read"
UCD_BILLING_AZ = "UCD-Billing"
UCD_READ_ONLY = "UCD-Read-Only"

role_defs = {
    UCD_FULL_ADMIN: {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": "*",
            "Resource": "*"
        },
        {
            "Sid": "DenyOrgAccountPermission1",
            "Effect": "Deny",
            "Action": "*",
            "Resource": [
                "arn:aws:iam::aws:policy/AWSOrganizationsFullAccess"
            ]
        }
        ]
    },
    UCD_BILLING: {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "AccountsAndBilling",
            "Effect": "Allow",
            "Action": [
                "budgets:View*",
                "budgets:Describe*",
                "budgets:ModifyBudget",
                "account:Get*",
                "account:List*",
                "billing:Get*",
                "billing:List*",
                "billing:RedeemCredits",
                "freetier:*",
                "invoicing:*",
                "payments:Get*",
                "payments:List*",
                "cur:*",
                "tax:List*",
                "tax:Get*",
                "support:Describe*",
                "support:Search*",
                "support:CreateCase",
                "support:AddAttachmentsToSet",
                "sustainability:GetCarbonFootprintSummary",
                "purchase-orders:List*",
                "purchase-orders:Get*",
                "purchase-orders:View*",
                "consolidatedbilling:*"
            ],
            "Resource": "*"
        },
        {
            "Sid": "CostExplorer",
            "Effect": "Allow",
            "Action": [
                "ce:Get*",
                "ce:Describe*",
                "ce:List*"
            ],
            "Resource": "*"
        },
        {
            "Sid": "PreJuly2023",
            "Effect": "Allow",
            "Action": [
                "budgets:ViewBudget",
                "aws-portal:*Usage",
                "aws-portal:*PaymentMethods",
                "aws-portal:ViewAccount",
                "cur:*",
                "aws-portal:*Billing",
                "budgets:ModifyBudget"
            ],
            "Resource": "*"
        }
        ]
    },
    UCD_OWNER: {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": "*",
            "Resource": "*"
        },
        {
            "Sid": "DenyOrgAccountPermission1",
            "Effect": "Deny",
            "Action": "*",
            "Resource": [
                "arn:aws:iam::aws:policy/AWSOrganizationsFullAccess"
            ]
        }
        ]
    }
}

trust_policy = {
    "XAccount-Trust": {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {
                "Federated": "%s"
            },
                "Action": "sts:AssumeRoleWithSAML",
                "Condition": {
                    "StringEquals": {
                    "SAML:aud": "https://signin.aws.amazon.com/saml"
                    }
                }
            }
        ]
    }
}
