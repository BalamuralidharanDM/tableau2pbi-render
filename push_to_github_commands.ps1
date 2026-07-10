# Run from this package root after creating an empty GitHub repository.
# Replace YOUR_GITHUB_REPO_URL with your repo URL.

git init
git add .
git commit -m "Deploy TABLEAU2PBI to Render"
git branch -M main
git remote add origin YOUR_GITHUB_REPO_URL
git push -u origin main
